import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.io_utils import load_inventory_df  # noqa: E402
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.streamlit_config import get_output_dir  # noqa: E402

st.set_page_config(page_title="Document Filter", layout="wide")

@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> List[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


@st.cache_data(show_spinner=False)
def cached_load_inventory(path_str: str) -> pd.DataFrame:
    return load_inventory_df(path_str)


# Helpers


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


def _numeric_series(df: pd.DataFrame, column: str, default: float = 0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype="float")
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def _safe_min_max(series: pd.Series) -> Optional[tuple]:
    if series.empty:
        return None
    min_val = series.min()
    max_val = series.max()
    if pd.isna(min_val) or pd.isna(max_val):
        return None
    return min_val, max_val


def _load_inventory_for_run(run_log: Dict) -> pd.DataFrame:
    inventory_path = run_log.get("inventory_path") if run_log else None
    if not inventory_path:
        return pd.DataFrame()
    try:
        return cached_load_inventory(inventory_path)
    except Exception as exc:  # pragma: no cover - user environment issue
        st.warning(f"Unable to load inventory at {inventory_path}: {exc}")
        return pd.DataFrame()


def _merge_inventory(docs_df: pd.DataFrame, inventory_df: pd.DataFrame) -> pd.DataFrame:
    if inventory_df.empty:
        merged = docs_df.copy()
        merged["size_mb"] = None
        merged["extension"] = None
        merged["detected_mime"] = None
        return merged

    inv_cols = [
        col
        for col in [
            "rel_path",
            "size_bytes",
            "extension",
            "detected_mime",
            "abs_path",
            "top_level_folder",
        ]
        if col in inventory_df.columns
    ]
    inventory_subset = inventory_df[inv_cols].copy()
    if "size_bytes" in inventory_subset.columns:
        inventory_subset["size_bytes"] = pd.to_numeric(inventory_subset["size_bytes"], errors="coerce")

    merged = docs_df.merge(inventory_subset, on="rel_path", how="left", suffixes=("", "_inventory"))
    if "size_bytes" in merged.columns:
        merged["size_mb"] = (merged["size_bytes"] / (1024 * 1024)).round(2)
    else:
        merged["size_mb"] = None

    if "abs_path" in merged.columns and "abs_path_inventory" in merged.columns:
        merged["abs_path"] = merged["abs_path"].fillna(merged["abs_path_inventory"])
    if "top_level_folder" in merged.columns and "top_level_folder_inventory" in merged.columns:
        merged["top_level_folder"] = merged["top_level_folder"].fillna(merged["top_level_folder_inventory"])

    if "extension" not in merged.columns:
        merged["extension"] = None
    if "detected_mime" not in merged.columns:
        merged["detected_mime"] = None

    return merged


# Page rendering


def main():
    st.title("Document Filter")
    st.caption("Filter probe-ready documents by content and inventory metrics without opening any files.")

    st.markdown(
        """
        Use this page to **narrow down which documents need attention**. Filters update the table in real time so
        reviewers can focus on long documents, low-text scans, or anything that falls outside expected ranges.
        """
    )

    picker = st.container()
    pick_cols = picker.columns([2, 2])
    out_dir = get_output_dir()
    with pick_cols[0]:
        st.caption("Output folder (from Configuration page)")
        st.code(str(out_dir), language="text")
        st.page_link("pages/00_Configuration.py", label="Update output folder", icon="🧭")
    runs = cached_list_probe_runs(str(out_dir))
    if not runs:
        picker.warning("No probe runs detected under this output folder yet.")
        st.stop()

    options = {_format_run_option(run): run for run in runs}
    labels = list(options.keys())
    selected_label = pick_cols[1].selectbox("Probe run", labels)
    selected_run = options[selected_label]

    docs_df, _pages_df, _summary, run_log = cached_load_probe_run(str(out_dir), selected_run["probe_run_id"])
    if docs_df.empty:
        st.warning("This probe run does not contain document-level metrics yet.")
        st.stop()

    inventory_df = _load_inventory_for_run(run_log)
    merged_df = _merge_inventory(docs_df, inventory_df)

    abs_paths = merged_df["abs_path"] if "abs_path" in merged_df.columns else pd.Series("", index=merged_df.index)
    rel_paths = merged_df["rel_path"] if "rel_path" in merged_df.columns else pd.Series("", index=merged_df.index)
    merged_df["reference_path"] = abs_paths.fillna("").astype(str)
    merged_df.loc[merged_df["reference_path"].eq(""), "reference_path"] = rel_paths.fillna("").astype(str)

    st.markdown("### Filters")
    st.caption("Adjust these sliders and selectors to focus on the documents you want to review first.")

    filter_cols = st.columns(3)
    page_counts = _numeric_series(merged_df, "page_count", 0)
    page_range = _safe_min_max(page_counts)
    if page_range:
        min_pages, max_pages = int(page_range[0]), int(page_range[1])
        if min_pages == max_pages:
            min_pages = max(min_pages - 1, 0)
            max_pages = max_pages + 1
        page_min, page_max = filter_cols[0].slider(
            "Document length (pages)",
            min_value=min_pages,
            max_value=max_pages,
            value=(min_pages, max_pages),
        )
    else:
        page_min, page_max = None, None
        filter_cols[0].info("No page count data available.")

    text_coverage = _numeric_series(merged_df, "text_coverage_pct", 0.0)
    text_range = _safe_min_max(text_coverage)
    if text_range:
        text_min, text_max = filter_cols[1].slider(
            "Text-based coverage (%)",
            min_value=0.0,
            max_value=1.0,
            value=(float(text_range[0]), float(text_range[1])),
            step=0.05,
        )
    else:
        text_min, text_max = None, None
        filter_cols[1].info("No text coverage data available.")

    classifications = sorted(merged_df.get("classification", pd.Series(dtype="string")).fillna("Unknown").unique())
    selected_classes = filter_cols[2].multiselect(
        "Document classification",
        options=classifications,
        default=classifications,
    )


    inv_cols = st.columns(3)
    size_series = _numeric_series(merged_df, "size_mb")
    size_range = _safe_min_max(size_series)
    if size_range:
        min_size, max_size = float(size_range[0]), float(size_range[1])
        if min_size == max_size:
            max_size = min_size + 1
        size_min, size_max = inv_cols[0].slider(
            "File size (MB)",
            min_value=0.0,
            max_value=max_size,
            value=(0.0, max_size),
            step=max(max_size / 20, 0.1),
        )
    else:
        size_min, size_max = None, None
        inv_cols[0].info("Inventory size data not found.")

    extensions = sorted(merged_df.get("extension", pd.Series(dtype="string")).fillna("(unknown)").unique())
    selected_extensions = inv_cols[1].multiselect(
        "Extension",
        options=extensions,
        default=extensions,
    )

    mime_types = sorted(merged_df.get("detected_mime", pd.Series(dtype="string")).fillna("(unknown)").unique())
    selected_mimes = inv_cols[2].multiselect(
        "Detected MIME",
        options=mime_types,
        default=mime_types,
    )

    filtered_df = merged_df.copy()
    if page_min is not None:
        filtered_df = filtered_df[(page_counts >= page_min) & (page_counts <= page_max)]
    if text_min is not None:
        filtered_df = filtered_df[(text_coverage >= text_min) & (text_coverage <= text_max)]
    if selected_classes:
        filtered_df = filtered_df[filtered_df["classification"].fillna("Unknown").isin(selected_classes)]
    if size_min is not None:
        filtered_df = filtered_df[(size_series >= size_min) & (size_series <= size_max)]
    if selected_extensions:
        filtered_df = filtered_df[filtered_df["extension"].fillna("(unknown)").isin(selected_extensions)]
    if selected_mimes:
        filtered_df = filtered_df[filtered_df["detected_mime"].fillna("(unknown)").isin(selected_mimes)]

    st.markdown("### Results")
    st.caption(
        "The table below lists each document and its reference path. Use the column picker to include more metrics if needed."
    )

    result_cols = st.columns(3)
    result_cols[0].metric("Documents matched", f"{filtered_df.shape[0]:,}")
    if "page_count" in filtered_df.columns:
        result_cols[1].metric("Total pages", f"{int(page_counts.loc[filtered_df.index].sum()):,}")
    if "text_coverage_pct" in filtered_df.columns:
        avg_text = text_coverage.loc[filtered_df.index].mean() if not filtered_df.empty else 0
        result_cols[2].metric("Average text coverage", f"{avg_text * 100:.1f}%")

    default_columns = [
        col
        for col in [
            "doc_id",
            "rel_path",
            "reference_path",
            "page_count",
            "text_coverage_pct",
            "classification",
            "size_mb",
            "extension",
            "detected_mime",
        ]
        if col in filtered_df.columns
    ]
    selectable_columns = [col for col in filtered_df.columns if col not in {"abs_path_inventory", "top_level_folder_inventory"}]
    selected_columns = st.multiselect(
        "Columns to display",
        options=selectable_columns,
        default=default_columns,
    )

    display_df = filtered_df[selected_columns].copy() if selected_columns else filtered_df.copy()
    if "text_coverage_pct" in display_df.columns:
        display_df["text_coverage_pct"] = (pd.to_numeric(display_df["text_coverage_pct"], errors="coerce") * 100).round(1)

    st.dataframe(display_df, use_container_width=True)
    st.caption("Percent columns are shown as percentages (0-100).")
    st.download_button(
        "Download filtered table as CSV",
        data=display_df.to_csv(index=False).encode("utf-8"),
        file_name="filtered_documents.csv",
    )


if __name__ == "__main__":
    main()
