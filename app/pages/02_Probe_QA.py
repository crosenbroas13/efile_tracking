import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.probe_viz_helpers import format_pct, safe_pct, safe_series  # noqa: E402

st.set_page_config(page_title="Probe QA", layout="wide")

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

    mostly_black_pages = summary.get("mostly_black_pages")
    if mostly_black_pages is None and "is_mostly_black" in pages_df.columns:
        mostly_black_pages = int(pages_df[pages_df["is_mostly_black"] == True].shape[0])  # noqa: E712
    mostly_black_pages = mostly_black_pages or 0
    black_pages_checked = 0
    if "is_mostly_black" in pages_df.columns:
        black_pages_checked = int(pages_df["is_mostly_black"].notna().sum())

    baseline_ocr = summary.get("estimated_ocr_pages_baseline")
    if baseline_ocr is None:
        baseline_ocr = max(total_pages - pages_with_text, 0)

    totals.update(
        {
            "classification_counts": summary.get("classification_counts", {}),
            "mostly_black_pages": mostly_black_pages,
            "mostly_black_pct": safe_pct(mostly_black_pages, black_pages_checked),
            "black_pages_checked": black_pages_checked,
            "pages_with_text": pages_with_text,
            "pages_without_text": max(total_pages - pages_with_text, 0),
            "estimated_ocr_pages_baseline": baseline_ocr,
            "estimated_ocr_pages_adjusted": summary.get("estimated_ocr_pages_adjusted", baseline_ocr),
            "ignored_non_pdf_files": summary.get("ignored_non_pdf_files", {}),
            "ignored_non_pdf_mime_types": summary.get("ignored_non_pdf_mime_types", {}),
            "ignored_non_pdf_total": summary.get("ignored_non_pdf_total", 0),
            "thresholds": summary.get("thresholds", {}),
        }
    )
    return totals


def _classification_breakdown(docs_df: pd.DataFrame, summary: Dict) -> Dict[str, int]:
    if summary.get("classification_counts"):
        return summary["classification_counts"]
    if "classification" in docs_df.columns:
        return docs_df["classification"].value_counts(dropna=False).to_dict()
    return {}


def _apply_issue_filter(df: pd.DataFrame, show_only_issues: bool, black_threshold: float) -> pd.DataFrame:
    if not show_only_issues:
        return df
    if df.empty:
        return df
    if "classification" in df.columns and "mostly_black_pct" in df.columns:
        return df[(df["classification"] != "Text-based") | (df["mostly_black_pct"] >= black_threshold)]
    if "classification" in df.columns:
        return df[df["classification"] != "Text-based"]
    return df


def _downloadable_table(df: pd.DataFrame, label: str):
    st.download_button(
        f"Download {label} as CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{label.replace(' ', '_').lower()}.csv",
    )


def _format_pct_or_na(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return format_pct(float(value))


# Page rendering

def main():
    st.title("Probe QA")
    st.caption("Explore probe outputs without recomputing anything. All data stays local.")

    st.markdown(
        """
        **Choose where to look:** point to the folder that already contains your probe outputs, then pick a run ID.
        This page only reads saved results on your machine—changing the folder simply switches which saved probes you are reviewing.
        """
    )

    picker = st.container()
    pick_cols = picker.columns([2, 2, 1])
    out_dir_text = pick_cols[0].text_input("Output folder", value=str(DEFAULT_OUT_DIR))
    runs = cached_list_probe_runs(out_dir_text)
    if not runs:
        picker.warning("No probe runs detected under this output folder yet.")
        st.stop()
    options = {_format_run_option(run): run for run in runs}
    labels = list(options.keys())
    selected_label = pick_cols[1].selectbox("Probe run", labels)
    selected_run = options[selected_label]

    summary = selected_run.get("summary", {})
    thresholds = summary.get("thresholds", {})
    text_threshold_default = int(thresholds.get("text_char_threshold", 25))
    black_ratio_default = float(thresholds.get("mostly_black_ratio", 0.9))

    with pick_cols[2]:
        st.markdown("**Display options**")
        show_mostly_black = st.checkbox("Mostly-black pages", value=False)
        exclude_black_from_ocr = st.checkbox("Skip black in OCR", value=True)
        show_only_issues = st.checkbox("Only issues", value=False)

    slider_cols = st.columns(2)
    text_char_threshold_display = slider_cols[0].slider(
        "Text character threshold (display only)", min_value=0, max_value=500, value=text_threshold_default, step=5
    )
    mostly_black_ratio_display = slider_cols[1].slider(
        "Mostly-black ratio (display only)", min_value=0.0, max_value=1.0, value=black_ratio_default, step=0.05
    )

    docs_df, pages_df, summary, run_log = cached_load_probe_run(out_dir_text, selected_run["probe_run_id"])
    totals = _compute_totals(docs_df, pages_df, summary)

    adjusted_ocr = totals.get("estimated_ocr_pages_adjusted", totals.get("estimated_ocr_pages_baseline", 0))
    if not exclude_black_from_ocr:
        adjusted_ocr = totals.get("estimated_ocr_pages_baseline", adjusted_ocr)

    st.subheader("Executive summary")
    metrics = st.columns(4)
    metrics[0].metric("PDFs processed", f"{totals['total_pdfs']:,}")
    metrics[1].metric("Pages processed", f"{totals['total_pages']:,}")
    metrics[2].metric(
        "Mostly-black pages",
        f"{totals.get('mostly_black_pages', 0):,}",
        format_pct(float(totals.get("mostly_black_pct", 0))),
    )
    metrics[3].metric(
        "Baseline OCR pages",
        f"{totals.get('estimated_ocr_pages_baseline', 0):,}",
        format_pct(safe_pct(totals.get("estimated_ocr_pages_baseline", 0), totals.get("total_pages", 0))),
    )

    metrics2 = st.columns(4)
    metrics2[0].metric(
        "Adjusted OCR pages",
        f"{adjusted_ocr:,}",
        format_pct(safe_pct(adjusted_ocr, totals.get("total_pages", 0))),
    )
    classification = _classification_breakdown(docs_df, summary)
    cls_text = " | ".join([f"{k}: {v}" for k, v in classification.items()]) if classification else "Unavailable"
    metrics2[1].metric("Doc classifications", cls_text)
    black_pages_checked = totals.get("black_pages_checked", 0)
    metrics2[2].metric(
        "Black pages checked",
        f"{black_pages_checked:,}",
        format_pct(safe_pct(black_pages_checked, totals.get("total_pages", 0))),
    )
    ignored_total = totals.get("ignored_non_pdf_total") or summary.get("ignored_non_pdf_total") or 0
    metrics2[3].metric("Ignored non-PDF artifacts", f"{ignored_total:,}")
    if totals.get("total_pages") and totals.get("black_pages_checked", 0) == 0:
        st.warning(
            "Mostly-black page metrics were not calculated for this run. "
            "This usually happens when the PDF rendering dependency is missing, "
            "so the probe could not analyze page pixels."
        )

    if totals.get("ignored_non_pdf_files"):
        st.markdown("#### Ignored non-PDF artifacts (by extension)")
        st.dataframe(pd.DataFrame([
            {"extension": ext or "(none)", "count": count} for ext, count in totals["ignored_non_pdf_files"].items()
        ]).sort_values("count", ascending=False), use_container_width=True)
    if totals.get("ignored_non_pdf_mime_types"):
        st.markdown("#### Ignored non-PDF artifacts (by MIME)")
        st.dataframe(pd.DataFrame([
            {"mime_type": mime or "(unknown)", "count": count} for mime, count in totals["ignored_non_pdf_mime_types"].items()
        ]).sort_values("count", ascending=False), use_container_width=True)

    st.divider()
    st.subheader("Distributions")
    chart_cols = st.columns(2)
    if "text_coverage_pct" in docs_df.columns and not docs_df.empty:
        fig = px.histogram(docs_df, x="text_coverage_pct", nbins=20, title="Document text coverage")
        chart_cols[0].plotly_chart(fig, use_container_width=True)
    else:
        chart_cols[0].info("No text coverage data available.")

    if "mostly_black_pct" in docs_df.columns and not docs_df.empty:
        fig_black = px.histogram(docs_df, x="mostly_black_pct", nbins=20, title="Document mostly-black ratio")
        chart_cols[1].plotly_chart(fig_black, use_container_width=True)
    else:
        chart_cols[1].info("No mostly-black ratios available.")

    chart_cols2 = st.columns(2)
    if "classification" in docs_df.columns:
        class_counts = docs_df["classification"].value_counts(dropna=False).reset_index()
        class_counts.columns = ["classification", "count"]
        fig_cls = px.bar(class_counts, x="classification", y="count", title="Documents by classification")
        chart_cols2[0].plotly_chart(fig_cls, use_container_width=True)
    else:
        chart_cols2[0].info("No classification column available.")

    if "top_level_folder" in pages_df.columns:
        pages_with_black = pages_df.copy()
        if "is_mostly_black" in pages_with_black.columns:
            pages_with_black["mostly_black"] = pages_with_black["is_mostly_black"].fillna(False)
        else:
            pages_with_black["mostly_black"] = False
        folder_counts = pages_with_black.groupby("top_level_folder").agg(
            pages=("page_num", "count"),
            mostly_black_pages=("mostly_black", "sum"),
        )
        folder_counts = folder_counts.reset_index().sort_values("pages", ascending=False)
        fig_folder = px.bar(
            folder_counts,
            x="top_level_folder",
            y=["pages", "mostly_black_pages"],
            barmode="group",
            title="Pages by top-level folder",
        )
        chart_cols2[1].plotly_chart(fig_folder, use_container_width=True)
    else:
        chart_cols2[1].info("Top-level folder data unavailable for pages.")

    st.divider()
    st.subheader("Prioritization tables")
    top_n = st.slider("Rows to display", min_value=5, max_value=100, value=20, step=5)

    def _prep_docs(df: pd.DataFrame) -> pd.DataFrame:
        base = df.copy()
        base["mostly_black_pct"] = pd.to_numeric(safe_series(base, "mostly_black_pct", None), errors="coerce")
        base["text_coverage_pct"] = pd.to_numeric(safe_series(base, "text_coverage_pct", 0), errors="coerce").fillna(0)
        base["page_count"] = pd.to_numeric(safe_series(base, "page_count", 0), errors="coerce").fillna(0)
        base["classification"] = safe_series(base, "classification", "Unknown")
        base["top_level_folder"] = safe_series(base, "top_level_folder", "")
        base["rel_path"] = safe_series(base, "rel_path", "")
        return base

    docs_ready = _prep_docs(_apply_issue_filter(docs_df, show_only_issues, mostly_black_ratio_display))

    best_candidates = docs_ready.sort_values(
        ["text_coverage_pct", "mostly_black_pct"], ascending=[False, True]
    ).head(top_n)
    st.markdown("#### Best candidates for fast extraction")
    st.dataframe(best_candidates[[
        "doc_id",
        "top_level_folder",
        "rel_path",
        "page_count",
        "text_coverage_pct",
        "mostly_black_pct",
        "classification",
    ]], use_container_width=True)
    _downloadable_table(best_candidates, "best_candidates")

    worst_candidates = docs_ready.sort_values(
        ["text_coverage_pct", "page_count"], ascending=[True, False]
    ).head(top_n)
    st.markdown("#### Worst candidates (likely scanned)")
    st.dataframe(worst_candidates[[
        "doc_id",
        "top_level_folder",
        "rel_path",
        "page_count",
        "text_coverage_pct",
        "mostly_black_pct",
        "classification",
    ]], use_container_width=True)
    _downloadable_table(worst_candidates, "worst_candidates")

    if "mostly_black_pct" in docs_ready.columns:
        most_redacted = docs_ready.sort_values("mostly_black_pct", ascending=False).head(top_n)
    else:
        most_redacted = pd.DataFrame()
    st.markdown("#### Most redacted / black-heavy")
    if most_redacted.empty:
        st.info("No mostly-black ratios available for this run.")
    else:
        st.dataframe(most_redacted[[
            "doc_id",
            "top_level_folder",
            "rel_path",
            "page_count",
            "text_coverage_pct",
            "mostly_black_pct",
            "classification",
        ]], use_container_width=True)
        _downloadable_table(most_redacted, "most_redacted")

    st.divider()
    st.subheader("Page-level drilldown")
    doc_options = {}
    for row in docs_df.fillna("").itertuples():
        label = f"{row.rel_path or row.doc_id} ({row.doc_id})"
        doc_options[label] = row.doc_id
    if not doc_options:
        st.info("No documents available in this run.")
    else:
        selected_doc = st.selectbox("Choose a document", list(doc_options.keys()))
        selected_doc_id = doc_options[selected_doc]
        doc_row = docs_df[docs_df["doc_id"] == selected_doc_id].iloc[0]
        doc_info_cols = st.columns(3)
        doc_info_cols[0].metric("Pages", int(doc_row.get("page_count", 0)))
        doc_info_cols[1].metric("Text coverage", format_pct(float(doc_row.get("text_coverage_pct", 0))))
        doc_info_cols[2].metric("Mostly-black", _format_pct_or_na(doc_row.get("mostly_black_pct")))

        if "doc_id" not in pages_df.columns:
            st.warning(
                "This probe run did not store per-page document IDs, so the page drilldown cannot filter pages for a single document."
            )
            doc_pages = pd.DataFrame()
        else:
            doc_pages = pages_df[pages_df["doc_id"] == selected_doc_id].copy()

        if doc_pages.empty:
            st.warning("No page-level data available for this document.")
        else:
            doc_pages["has_text_display"] = doc_pages.get("text_char_count", 0) >= text_char_threshold_display
            if "black_ratio" in doc_pages.columns:
                doc_pages["is_mostly_black_display"] = doc_pages["black_ratio"] >= mostly_black_ratio_display
            else:
                doc_pages["is_mostly_black_display"] = False

            col_filters = st.columns(3)
            only_no_text = col_filters[0].checkbox("Only pages without text", value=False)
            only_black = col_filters[1].checkbox("Only mostly-black", value=show_mostly_black)
            needs_ocr = col_filters[2].checkbox("Only pages needing OCR", value=False)

            filtered_pages = doc_pages.copy()
            if only_no_text:
                filtered_pages = filtered_pages[filtered_pages["has_text_display"] == False]  # noqa: E712
            if only_black:
                filtered_pages = filtered_pages[filtered_pages["is_mostly_black_display"] == True]  # noqa: E712
            if needs_ocr and "has_text" in filtered_pages.columns:
                filtered_pages = filtered_pages[(filtered_pages["has_text"] == False) | (filtered_pages["is_mostly_black_display"] == True)]  # noqa: E712

            display_cols = ["page_num", "has_text", "text_char_count", "is_mostly_black"]
            if "black_ratio" in filtered_pages.columns:
                display_cols.insert(3, "black_ratio")
            st.dataframe(filtered_pages[display_cols], use_container_width=True)

    st.divider()
    st.subheader("Run log & reproducibility")
    log_cols = st.columns(2)
    log_cols[0].write({
        "Inventory": run_log.get("inventory_path"),
        "Output root": run_log.get("output_root"),
        "Git commit": run_log.get("git_commit"),
        "Timestamp": run_log.get("timestamp"),
        "Args": (run_log.get("config") or {}),
    })
    meta = run_log.get("meta") or {}
    log_cols[1].write({
        "Runtime (s)": meta.get("probe_run_seconds"),
        "Errors": meta.get("error_count"),
        "Ignored non-PDF": meta.get("ignored_non_pdf_total"),
    })

    if meta.get("errors"):
        st.markdown("#### Errors (sample)")
        st.json(meta.get("errors_sample") or meta.get("errors"))


if __name__ == "__main__":
    main()
