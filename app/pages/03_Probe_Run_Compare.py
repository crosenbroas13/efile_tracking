import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.probe_viz_helpers import format_pct, safe_series  # noqa: E402

st.set_page_config(page_title="Probe Run Compare", layout="wide")

DEFAULT_OUT_DIR = Path("./outputs")


@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> List[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


# UI helpers

def _format_run_option(run: Dict) -> str:
    ts = run.get("timestamp")
    ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "(time unknown)"
    summary = run.get("summary") or {}
    pdfs = summary.get("total_pdfs")
    pages = summary.get("total_pages")
    extras = []
    if pdfs is not None:
        extras.append(f"{pdfs} PDFs")
    if pages is not None:
        extras.append(f"{pages} pages")
    extra_text = " | ".join(extras) if extras else "no counts"
    return f"{run.get('probe_run_id')} – {ts_text} – {extra_text}"


def _compute_totals(docs_df: pd.DataFrame, pages_df: pd.DataFrame, summary: Dict) -> Dict:
    totals: Dict[str, float] = {}
    totals["total_pdfs"] = summary.get("total_pdfs", len(docs_df))
    total_pages = summary.get("total_pages", len(pages_df))
    if (not total_pages) and "page_count" in docs_df.columns:
        total_pages = int(pd.to_numeric(docs_df["page_count"], errors="coerce").fillna(0).sum())
    totals["total_pages"] = total_pages

    pages_with_text = summary.get("pages_with_text")
    if pages_with_text is None and "has_text" in pages_df.columns:
        pages_with_text = int(pages_df[pages_df["has_text"] == True].shape[0])  # noqa: E712
    if pages_with_text is None and "pages_with_text" in docs_df.columns:
        pages_with_text = int(pd.to_numeric(docs_df["pages_with_text"], errors="coerce").fillna(0).sum())
    pages_with_text = pages_with_text or 0

    baseline_ocr = summary.get("estimated_ocr_pages_baseline")
    if baseline_ocr is None:
        baseline_ocr = max(total_pages - pages_with_text, 0)

    totals.update(
        {
            "pages_with_text": pages_with_text,
            "pages_without_text": max(total_pages - pages_with_text, 0),
            "estimated_ocr_pages_baseline": baseline_ocr,
            "classification_counts": summary.get("classification_counts", {}),
        }
    )
    return totals


def _format_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}"


def _format_pct_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _prep_docs(df: pd.DataFrame) -> pd.DataFrame:
    base = df.copy()
    base["doc_id"] = safe_series(base, "doc_id", "").astype(str)
    base["rel_path"] = safe_series(base, "rel_path", "")
    base["top_level_folder"] = safe_series(base, "top_level_folder", "")
    base["page_count"] = pd.to_numeric(safe_series(base, "page_count", 0), errors="coerce").fillna(0)
    base["text_coverage_pct"] = pd.to_numeric(safe_series(base, "text_coverage_pct", 0), errors="coerce").fillna(0)
    base["classification"] = safe_series(base, "classification", "Unknown")
    return base


# Page rendering

def main():
    st.title("Probe Run Comparison")
    st.caption("Compare two probe runs side-by-side. Nothing is reprocessed; the page only reads saved outputs.")

    st.markdown(
        """
        **Use this page when you want to explain change over time.**
        Pick two probe runs and we will highlight what shifted in totals, text readiness, and document-level metrics.
        The summary is designed for non-technical reviewers who need to understand impact without looking at raw files.
        """
    )

    picker = st.container()
    pick_cols = picker.columns([2, 2, 2])
    out_dir_text = pick_cols[0].text_input("Output folder", value=str(DEFAULT_OUT_DIR))
    runs = cached_list_probe_runs(out_dir_text)
    if len(runs) < 2:
        picker.warning("Need at least two probe runs under this output folder to compare.")
        st.stop()

    options = {_format_run_option(run): run for run in runs}
    labels = list(options.keys())
    run_a_label = pick_cols[1].selectbox("Baseline run", labels, index=0)
    run_b_label = pick_cols[2].selectbox("Comparison run", labels, index=1 if len(labels) > 1 else 0)
    run_a = options[run_a_label]
    run_b = options[run_b_label]

    if run_a["probe_run_id"] == run_b["probe_run_id"]:
        st.info("Pick two different runs to see differences.")
        st.stop()

    docs_a, pages_a, summary_a, run_log_a = cached_load_probe_run(out_dir_text, run_a["probe_run_id"])
    docs_b, pages_b, summary_b, run_log_b = cached_load_probe_run(out_dir_text, run_b["probe_run_id"])

    totals_a = _compute_totals(docs_a, pages_a, summary_a)
    totals_b = _compute_totals(docs_b, pages_b, summary_b)

    st.subheader("Executive comparison")
    summary_rows = []
    for key, label, is_pct in [
        ("total_pdfs", "PDFs processed", False),
        ("total_pages", "Pages processed", False),
        ("pages_with_text", "Pages with text", False),
        ("pages_without_text", "Pages without text", False),
        ("estimated_ocr_pages_baseline", "Baseline OCR pages", False),
    ]:
        value_a = totals_a.get(key, 0)
        value_b = totals_b.get(key, 0)
        delta = value_b - value_a
        if is_pct:
            summary_rows.append(
                {
                    "Metric": label,
                    "Baseline": format_pct(value_a),
                    "Comparison": format_pct(value_b),
                    "Delta": _format_pct_delta(delta),
                }
            )
        else:
            summary_rows.append(
                {
                    "Metric": label,
                    "Baseline": f"{value_a:,}",
                    "Comparison": f"{value_b:,}",
                    "Delta": _format_delta(delta),
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(summary_df, use_container_width=True)
    st.download_button(
        "Download executive comparison as CSV",
        summary_df.to_csv(index=False).encode("utf-8"),
        file_name="probe_run_comparison_summary.csv",
    )

    st.markdown(
        """
        **How to read the table:**
        - *Baseline* is the earlier or reference run.
        - *Comparison* is the newer run.
        - *Delta* shows what changed; positive numbers mean the metric increased.
        """
    )

    st.divider()
    st.subheader("Classification shifts")
    class_counts = {}
    for label, totals in [("Baseline", totals_a), ("Comparison", totals_b)]:
        for cls, count in (totals.get("classification_counts") or {}).items():
            class_counts.setdefault(cls, {})[label] = count

    if not class_counts:
        st.info("No classification breakdown stored for these runs.")
    else:
        class_rows = []
        for cls in sorted(class_counts.keys()):
            base = class_counts[cls].get("Baseline", 0)
            comp = class_counts[cls].get("Comparison", 0)
            class_rows.append(
                {
                    "Classification": cls,
                    "Baseline": f"{base:,}",
                    "Comparison": f"{comp:,}",
                    "Delta": _format_delta(comp - base),
                }
            )
        class_df = pd.DataFrame(class_rows)
        st.dataframe(class_df, use_container_width=True)
        st.download_button(
            "Download classification shifts as CSV",
            class_df.to_csv(index=False).encode("utf-8"),
            file_name="probe_run_comparison_classifications.csv",
        )

    st.divider()
    st.subheader("Document-level changes")
    st.markdown(
        """
        The table below highlights documents that changed the most between runs. This is useful when
        you want to explain **which files got better or worse** without inspecting every PDF.
        """
    )

    docs_base = _prep_docs(docs_a)
    docs_comp = _prep_docs(docs_b)
    merged = docs_base.merge(
        docs_comp,
        on="doc_id",
        how="outer",
        suffixes=("_base", "_comp"),
        indicator=True,
    )
    merged["status"] = merged["_merge"].map(
        {"left_only": "Only in baseline", "right_only": "Only in comparison", "both": "In both"}
    )
    merged["delta_text_coverage"] = merged["text_coverage_pct_comp"].fillna(0) - merged[
        "text_coverage_pct_base"
    ].fillna(0)
    merged["delta_page_count"] = merged["page_count_comp"].fillna(0) - merged["page_count_base"].fillna(0)

    table_cols = [
        "doc_id",
        "status",
        "top_level_folder_base",
        "rel_path_base",
        "classification_base",
        "classification_comp",
        "page_count_base",
        "page_count_comp",
        "delta_page_count",
        "text_coverage_pct_base",
        "text_coverage_pct_comp",
        "delta_text_coverage",
    ]

    top_change = st.slider("Highlight top N changes", min_value=10, max_value=200, value=50, step=10)
    change_focus = st.selectbox(
        "Focus on",
        ["Largest text coverage shifts", "Largest page count shifts"],
    )

    if change_focus == "Largest page count shifts":
        sort_key = "delta_page_count"
    else:
        sort_key = "delta_text_coverage"

    changes = merged[merged["status"] == "In both"].copy()
    changes["abs_change"] = changes[sort_key].abs()
    changes = changes.sort_values("abs_change", ascending=False).head(top_change)

    if changes.empty:
        st.info("No overlapping documents found between these runs.")
    else:
        display = changes[table_cols].copy()
        st.dataframe(display, use_container_width=True)
        st.download_button(
            "Download document change highlights as CSV",
            display.to_csv(index=False).encode("utf-8"),
            file_name="probe_run_document_changes.csv",
        )

    st.divider()
    st.subheader("Documents that appear only once")
    missing_cols = [
        "doc_id",
        "status",
        "top_level_folder_base",
        "rel_path_base",
        "top_level_folder_comp",
        "rel_path_comp",
        "classification_base",
        "classification_comp",
        "page_count_base",
        "page_count_comp",
    ]
    missing_docs = merged[merged["status"] != "In both"]
    if missing_docs.empty:
        st.success("All documents are present in both runs.")
    else:
        st.dataframe(missing_docs[missing_cols], use_container_width=True)
        st.download_button(
            "Download missing documents as CSV",
            missing_docs[missing_cols].to_csv(index=False).encode("utf-8"),
            file_name="probe_run_missing_docs.csv",
        )

    st.divider()
    st.subheader("Run metadata")
    log_cols = st.columns(2)
    log_cols[0].write(
        {
            "Baseline run": run_a["probe_run_id"],
            "Inventory": run_log_a.get("inventory_path"),
            "Output root": run_log_a.get("output_root"),
            "Git commit": run_log_a.get("git_commit"),
            "Timestamp": run_log_a.get("timestamp"),
        }
    )
    log_cols[1].write(
        {
            "Comparison run": run_b["probe_run_id"],
            "Inventory": run_log_b.get("inventory_path"),
            "Output root": run_log_b.get("output_root"),
            "Git commit": run_log_b.get("git_commit"),
            "Timestamp": run_log_b.get("timestamp"),
        }
    )


if __name__ == "__main__":
    main()
