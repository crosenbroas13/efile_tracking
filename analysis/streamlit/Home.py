import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.doj_doc_explorer.utils.paths import normalize_rel_path  # noqa: E402
from src.io_utils import (  # noqa: E402
    format_run_label,
    load_inventory_df,
    pick_default_inventory,
)
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.qa_metrics import rollup_by_top_level  # noqa: E402
from src.streamlit_config import get_output_dir  # noqa: E402
from src.text_scan_io import load_latest_text_scan  # noqa: E402

st.set_page_config(page_title="DOJ Toolkit", layout="wide")


@st.cache_data(show_spinner=False)
def _cached_list_probe_runs(out_dir_str: str):
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def _cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


@st.cache_data(show_spinner=False)
def _cached_load_latest_text_scan(out_dir_str: str):
    return load_latest_text_scan(out_dir_str)


def _format_pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0%"
    return f"{(numerator / denominator) * 100:.0f}%"


def _load_latest_inventory(out_dir: Path):
    default_path = pick_default_inventory(out_dir)
    if not default_path:
        return pd.DataFrame(), None
    return load_inventory_df(default_path), format_run_label(default_path)


def _load_latest_probe(out_dir: Path):
    runs = _cached_list_probe_runs(str(out_dir))
    if not runs:
        return pd.DataFrame(), None
    latest_run = runs[0]
    docs_df, _pages_df, _summary, run_log = _cached_load_probe_run(str(out_dir), latest_run["probe_run_id"])
    return docs_df, run_log


def _merge_text_scan_labels(docs_df: pd.DataFrame, text_scan_df: pd.DataFrame) -> pd.DataFrame:
    if docs_df.empty or text_scan_df.empty:
        return docs_df
    if "rel_path" not in docs_df.columns or "rel_path" not in text_scan_df.columns:
        return docs_df
    docs_df = docs_df.copy()
    text_scan_df = text_scan_df.copy()
    docs_df["rel_path_norm"] = docs_df["rel_path"].astype(str).map(normalize_rel_path)
    text_scan_df["rel_path_norm"] = text_scan_df["rel_path"].astype(str).map(normalize_rel_path)
    text_scan_df = text_scan_df.drop_duplicates(subset=["rel_path_norm"])
    merge_cols = ["text_quality_label"]
    available_cols = [col for col in merge_cols if col in text_scan_df.columns and col not in docs_df.columns]
    if not available_cols:
        return docs_df.drop(columns=["rel_path_norm"], errors="ignore")
    merged = docs_df.merge(text_scan_df[available_cols + ["rel_path_norm"]], on="rel_path_norm", how="left")
    return merged.drop(columns=["rel_path_norm"], errors="ignore")


st.title("DOJ VOL Folder QA Toolkit")
st.caption("Latest inventory and probe snapshot for fast, non-technical review.")

st.markdown(
    """
    **What this page does:** it automatically pulls the newest inventory and probe outputs so reviewers can
    understand *what is in the drop*, *where the files live*, and *which PDFs are truly text-ready* without
    opening documents or running new analysis.
    """
)

with st.expander("Data sources", expanded=True):
    st.markdown(
        """
        The dashboards read files stored on your machine only. Set the output folder once on the
        Configuration page if your runs live somewhere other than the default `./outputs`.
        """
    )
    out_dir = get_output_dir()
    st.code(str(out_dir), language="text")
    st.page_link("pages/00_Configuration.py", label="Update output folder", icon="🧭")

inventory_df, inventory_label = _load_latest_inventory(out_dir)
if inventory_df.empty:
    st.warning("No inventory found yet. Run an inventory to populate the dashboard.")
    st.stop()

probe_docs_df, probe_run_log = _load_latest_probe(out_dir)

st.markdown("### Executive Summary")
st.caption("Quick totals for the newest inventory run.")
total_files = len(inventory_df)
total_bytes = pd.to_numeric(inventory_df.get("size_bytes", pd.Series(dtype="float")), errors="coerce").fillna(0)
total_size_gb = total_bytes.sum() / (1024**3)
summary_cols = st.columns(2)
summary_cols[0].metric("Total file count", f"{total_files:,}")
summary_cols[1].metric("Total size", f"{total_size_gb:,.2f} GB")
if inventory_label:
    st.caption(f"Using latest inventory: {inventory_label}")

st.markdown("### VOL Folder Structure")
st.caption("Folder mix by file count, plus the largest folders by total size.")
structure_cols = st.columns(2)

with structure_cols[0]:
    folder_counts = (
        inventory_df.get("top_level_folder", pd.Series(dtype="string"))
        .fillna("Unknown")
        .value_counts()
        .reset_index()
    )
    folder_counts.columns = ["top_level_folder", "files"]
    if folder_counts.empty:
        st.info("No top-level folder data available in this inventory.")
    else:
        folder_counts["percent_of_files"] = (folder_counts["files"] / folder_counts["files"].sum()) * 100
        pie_fig = px.pie(
            folder_counts,
            names="top_level_folder",
            values="files",
            title="Share of files by top-level folder",
            hole=0.35,
        )
        pie_fig.update_traces(texttemplate="%{percent:.0%}")
        st.plotly_chart(pie_fig, use_container_width=True)

with structure_cols[1]:
    size_rollup = rollup_by_top_level(inventory_df)
    if size_rollup.empty:
        st.info("No folder size rollup available.")
    else:
        size_rollup["total_size_gb"] = (size_rollup["total_bytes"] / (1024**3)).round(2)
        size_rollup["percent_of_total"] = size_rollup["percent_of_total"].round(0).astype(int)
        top_folders = size_rollup.head(5)
        st.markdown("**Top 5 largest folders**")
        st.dataframe(
            top_folders[["top_level_folder", "files", "total_size_gb", "percent_of_total"]]
            .rename(
                columns={
                    "top_level_folder": "Folder",
                    "files": "Files",
                    "total_size_gb": "Size (GB)",
                    "percent_of_total": "% of total size",
                }
            ),
            use_container_width=True,
        )

st.markdown("### Files by Type")
st.caption("Counts of extensions stacked by top-level folder to show where file types cluster.")
if "extension" not in inventory_df.columns or "top_level_folder" not in inventory_df.columns:
    st.info("Extension or folder fields are missing from this inventory.")
else:
    ext_counts = (
        inventory_df.assign(
            extension=inventory_df["extension"].fillna("(none)").str.lower(),
            top_level_folder=inventory_df["top_level_folder"].fillna("Unknown"),
        )
        .groupby(["extension", "top_level_folder"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    top_extensions = (
        ext_counts.groupby("extension", as_index=False)["count"].sum().sort_values("count", ascending=False).head(12)
    )
    ext_counts = ext_counts[ext_counts["extension"].isin(top_extensions["extension"])]
    bar_fig = px.bar(
        ext_counts,
        x="extension",
        y="count",
        color="top_level_folder",
        title="File counts by extension (top 12)",
    )
    bar_fig.update_layout(barmode="stack", xaxis_title="Extension", yaxis_title="Files")
    st.plotly_chart(bar_fig, use_container_width=True)

st.markdown("### Text Based PDF Documents")
st.caption("Text-ready PDFs from the latest probe, verified with the most recent Text Scan when available.")
if probe_docs_df.empty:
    st.info("No probe run detected yet. Run a probe to see text readiness metrics.")
else:
    text_scan_df, _text_scan_summary, _text_scan_run_log = _cached_load_latest_text_scan(str(out_dir))
    probe_docs_df = _merge_text_scan_labels(probe_docs_df, text_scan_df)
    if "classification" not in probe_docs_df.columns:
        st.info("Probe results are missing document classification fields.")
    else:
        text_docs_df = probe_docs_df[probe_docs_df["classification"] == "Text-based"].copy()
        text_docs_df["text_quality_label"] = text_docs_df.get("text_quality_label", "").fillna("")
        verified_df = text_docs_df[text_docs_df["text_quality_label"] == "GOOD"]
        suspicious_df = text_docs_df[text_docs_df["text_quality_label"].isin(["EMPTY", "LOW"])]

        text_based_count = len(text_docs_df)
        verified_count = len(verified_df)
        suspicious_count = len(suspicious_df)

        metric_cols = st.columns(3)
        metric_cols[0].metric("Probe text-based internal_docs", f"{text_based_count:,}")
        metric_cols[1].metric(
            "Verified good text (GOOD)",
            f"{verified_count:,} ({_format_pct(verified_count, text_based_count)})",
        )
        metric_cols[2].metric(
            "Suspicious text (EMPTY/LOW)",
            f"{suspicious_count:,} ({_format_pct(suspicious_count, text_based_count)})",
        )

        overall_pct = _format_pct(text_based_count, total_files)
        st.markdown(
            f"**Overall text-based share:** {text_based_count:,} probe text-based PDFs are **{overall_pct}** of total inventory documents."
        )
        if probe_run_log:
            st.caption(f"Latest probe run ID: {probe_run_log.get('probe_run_id', 'unknown')}")

st.divider()
st.markdown(
    """
    **Need deeper detail?** Use the navigation sidebar to open the Inventory QA, Probe QA, and Text Based Documents pages.
    These views stay local to your machine and avoid uploading any document contents.
    """
)
