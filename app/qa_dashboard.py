"""Streamlit dashboard for inspecting inventory outputs."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import pandas as pd
import plotly.express as px
import streamlit as st

from src.io_utils import (
    DEFAULT_OUT_DIR,
    format_run_label,
    list_inventory_candidates,
    load_inventory_df,
    load_run_log,
    normalize_out_dir,
    pick_default_inventory,
)
from src.qa_metrics import (
    IssueConfig,
    compute_executive_summary,
    counts_by_extension_and_mime,
    deepest_paths,
    detect_potential_issues,
    find_duplicate_groups,
    largest_files,
    rollup_by_top_level,
    size_histogram,
)

st.set_page_config(page_title="Dataset QA Report", layout="wide")

CONFIG_DEFAULTS = {
    "large_file_threshold": 500,  # MB
}


def _load_selected_inventory(selected_path: Path | None) -> pd.DataFrame:
    if selected_path is None:
        return pd.DataFrame()
    return load_inventory_df(selected_path)


def _compute_error_count(run_logs: list[Dict]) -> int:
    if not run_logs:
        return 0
    latest = run_logs[0]
    return int(latest.get("errors_count", 0))


def _initial_out_dir_from_args() -> Path:
    args = sys.argv[1:]
    for idx, arg in enumerate(args):
        if arg in {"--out", "-o"} and idx + 1 < len(args):
            return normalize_out_dir(args[idx + 1])
    return DEFAULT_OUT_DIR


def main() -> None:
    st.title("Dataset QA Report")
    st.caption("Local-only dashboard that summarizes inventory outputs without reading file contents.")

    with st.sidebar:
        st.header("Inputs")
        default_out = _initial_out_dir_from_args()
        out_dir_text = st.text_input("Output folder", value=str(default_out))
        out_dir = normalize_out_dir(out_dir_text)

        candidates = list_inventory_candidates(out_dir)
        options = {format_run_label(p): p for p in candidates}
        default_path = pick_default_inventory(out_dir)
        default_label = format_run_label(default_path) if default_path else None
        option_keys = list(options.keys())
        default_index = 0
        if default_label and default_label in option_keys:
            default_index = option_keys.index(default_label)
        selection = st.selectbox(
            "Inventory run",
            options=option_keys or ["No inventory found"],
            index=default_index,
        )
        selected_path = options.get(selection)

        use_hash_duplicates = st.checkbox("Treat same-hash files as duplicates", value=True)
        show_only_issues = st.checkbox("Show only potential issues", value=False)
        top_n = st.slider("Top N", min_value=5, max_value=100, value=20, step=5)

        with st.expander("QA thresholds"):
            large_mb = st.number_input(
                "Very large file threshold (MB)",
                min_value=1,
                value=CONFIG_DEFAULTS["large_file_threshold"],
                step=50,
            )

    if not selected_path:
        st.warning("No inventory.csv found in the selected output folder. Run the inventory pipeline first.")
        return

    df = _load_selected_inventory(selected_path)
    if df.empty:
        st.info("The inventory file is empty.")
        return

    run_logs = load_run_log(out_dir)
    errors_count = _compute_error_count(run_logs)

    issue_config = IssueConfig(large_file_threshold=int(large_mb * 1024 * 1024))
    issues_df = detect_potential_issues(df, issue_config)
    filtered_df = df
    if show_only_issues and not issues_df.empty:
        filtered_df = df[df["rel_path"].isin(issues_df["rel_path"])]

    st.markdown("### Executive Summary")
    summary = compute_executive_summary(df, errors_count=errors_count)
    cat_counts = summary.get("file_type_counts", {})
    metrics_cols = st.columns(5)
    metrics_cols[0].metric("Total files", f"{summary['total_files']:,}")
    metrics_cols[1].metric("Total size", f"{summary['total_size_gb']:.2f} GB")
    metrics_cols[2].metric("PDF / Text / CSV / Images", f"{cat_counts.get('pdf', 0)} / {cat_counts.get('text', 0)} / {cat_counts.get('csv', 0)} / {cat_counts.get('image', 0)}")
    metrics_cols[3].metric("Top-level folders", str(summary.get("top_level_folders", 0)))
    metrics_cols[4].metric("Logged errors", str(summary.get("errors_count", 0)))

    st.markdown("### Dataset Structure")
    rollup = rollup_by_top_level(filtered_df)
    st.subheader("Top-level folder rollup")
    st.dataframe(rollup)
    if not rollup.empty:
        fig = px.bar(rollup, x="top_level_folder", y="total_bytes", title="Bytes by top-level folder")
        fig.update_layout(yaxis_title="Bytes", xaxis_title="Folder")
        st.plotly_chart(fig, use_container_width=True)

    deep_table = deepest_paths(filtered_df, n=top_n)
    st.subheader("Deepest folder paths")
    st.caption("Helps spot messy nesting or scattered files.")
    st.dataframe(deep_table)

    st.markdown("### File Type & Size QA")
    counts_table = counts_by_extension_and_mime(filtered_df)
    st.subheader("Counts by extension and MIME")
    st.dataframe(counts_table)

    st.subheader("File size histogram")
    histogram = size_histogram(filtered_df)
    if not histogram.empty:
        hist_df = histogram.reset_index().rename(columns={"index": "size_band", 0: "count"})
        hist_df.columns = ["size_band", "count"]
        st.bar_chart(hist_df.set_index("size_band"))
    else:
        st.info("No size data available for histogram.")

    st.subheader("Top largest files")
    st.dataframe(largest_files(filtered_df, top_n=top_n))

    st.markdown("### Duplicates & Integrity")
    if "hash_value" in df.columns:
        dup_df = find_duplicate_groups(df, use_hash=use_hash_duplicates)
        st.write(f"Duplicate groups found: {len(dup_df)}")
        st.dataframe(dup_df.head(top_n))
    else:
        st.warning("Hash column missing. Rerun the inventory with hashing enabled to detect duplicates.")

    st.markdown("### Potential Issues")
    if issues_df.empty:
        st.success("No obvious issues detected based on current rules.")
    else:
        st.dataframe(issues_df)
        st.download_button("Download flagged rows", issues_df.to_csv(index=False), file_name="potential_issues.csv")

    st.markdown("### Run History")
    if run_logs:
        history_cols = ["timestamp", "root", "args", "runtime_seconds", "files_scanned", "errors_count", "git_commit"]
        history_df = pd.DataFrame(run_logs)[history_cols].head(10)
        st.dataframe(history_df)
        st.caption(f"Currently viewing: {selection}")
    else:
        st.info("No run_log.jsonl entries found in this output folder.")


if __name__ == "__main__":
    main()
