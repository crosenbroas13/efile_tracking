import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.doj_doc_explorer.pdf_type.labels import (
    LABEL_VALUES,
    filter_pdf_inventory,
    inventory_identity,
    labels_path,
    load_labels,
    match_labels_to_inventory,
    normalize_labels_for_save,
    reconcile_labels,
    write_labels,
)
from src.doj_doc_explorer.utils.paths import normalize_rel_path
from src.io_utils import (
    DEFAULT_OUT_DIR,
    format_run_label,
    list_inventory_candidates,
    load_inventory_df,
    normalize_out_dir,
    pick_default_inventory,
)
from src.probe_readiness import stable_doc_id

st.set_page_config(page_title="PDF Labeling", layout="wide")


def _initial_out_dir_from_args() -> Path:
    args = sys.argv[1:]
    for idx, arg in enumerate(args):
        if arg in {"--out", "-o"} and idx + 1 < len(args):
            return normalize_out_dir(args[idx + 1])
    return DEFAULT_OUT_DIR


def _compute_doc_id_from_row(row: pd.Series) -> str:
    series = pd.Series(
        {
            "sha256": row.get("sha256"),
            "rel_path": row.get("rel_path"),
            "size_bytes": row.get("size_bytes"),
            "modified_time": row.get("modified_time"),
        }
    )
    return stable_doc_id(series)


def _build_inventory_selector(out_dir: Path) -> tuple[Path | None, str | None]:
    candidates = list_inventory_candidates(out_dir)
    options = {format_run_label(p): p for p in candidates}
    default_path = pick_default_inventory(out_dir)
    default_label = format_run_label(default_path) if default_path else None
    option_keys = list(options.keys())
    default_index = 0
    if default_label and default_label in option_keys:
        default_index = option_keys.index(default_label)
    selection = st.selectbox(
        "Inventory run (auto-detected from output folder)",
        options=option_keys or ["No inventory found"],
        index=default_index,
        help="Choose the inventory that matches the PDFs you want to label.",
    )
    return options.get(selection), selection


st.title("PDF Type Labeling")
st.caption("Friendly workspace for applying human-reviewed labels and saving them to the master labels file.")

st.markdown(
    """
    Use this page to confirm whether a PDF is **text-based**, **image-based**, or **mixed**.
    Every label you apply is written to a master CSV file that can be reused across reruns,
    so reviewers do not have to repeat work.
    """
)

st.markdown("### 1) Choose the inventory you are labeling")
st.caption("Pick the same output folder used for inventory and probe runs so the labels stay aligned.")

selector = st.container()
with selector:
    input_cols = st.columns([2, 2])
    with input_cols[0]:
        out_dir_text = st.text_input("Output folder", value=str(_initial_out_dir_from_args()))
        out_dir = normalize_out_dir(out_dir_text)
    with input_cols[1]:
        selected_path, selection_label = _build_inventory_selector(out_dir)

if not selected_path:
    st.warning("No inventory.csv found. Run an inventory first, then return to this page.")
    st.stop()

inventory_df = load_inventory_df(selected_path)
inventory_df = filter_pdf_inventory(inventory_df)
if inventory_df.empty:
    st.warning("The selected inventory does not contain any PDFs to label.")
    st.stop()

inventory_df["rel_path"] = inventory_df["rel_path"].astype(str).map(normalize_rel_path)
inventory_id = inventory_identity(selected_path)

labels_csv = labels_path(out_dir)
labels_df = load_labels(labels_csv, inventory_df)

st.markdown("### 2) Apply a label")
st.caption("Pick a PDF, choose a label, and save it to the master file. Notes are optional but helpful.")

filter_text = st.text_input(
    "Filter PDFs by folder or filename",
    value="",
    help="Type part of a path to narrow the list, especially for large inventories.",
)

inventory_ui = inventory_df.copy()
label_lookup = labels_df.set_index("rel_path")["label"].to_dict() if not labels_df.empty else {}
inventory_ui["current_label"] = inventory_ui["rel_path"].map(label_lookup).fillna("")
inventory_ui["is_labeled"] = inventory_ui["current_label"].astype(str).str.strip() != ""

show_labeled = st.checkbox(
    "Include already labeled PDFs",
    value=False,
    help="Turn this on only when you need to review or update existing labels.",
)

candidate_df = inventory_ui if show_labeled else inventory_ui[~inventory_ui["is_labeled"]].copy()
if filter_text:
    candidate_df = candidate_df[candidate_df["rel_path"].str.contains(filter_text, case=False, na=False)]

candidate_df = candidate_df.sort_values("rel_path")
candidate_paths = candidate_df["rel_path"].tolist()

with st.form("apply_label"):
    rel_path = st.selectbox(
        "PDF to label",
        options=candidate_paths or ["No matching PDFs found"],
        help="If the list is long, use the filter above to narrow it.",
    )
    label_value = st.selectbox("Label", options=sorted(LABEL_VALUES))
    notes = st.text_area("Reviewer notes (optional)", help="Record anything that helps explain your choice later.")
    source_probe_run = st.text_input(
        "Source probe run ID (optional)",
        help="If a probe run informed the decision, paste the run ID here for traceability.",
    )
    labeling_version = st.text_input(
        "Labeling schema version (optional)",
        help="Use this if your team tracks different labeling guidelines over time.",
    )
    overwrite = st.checkbox("Overwrite existing label if one exists")
    submitted = st.form_submit_button("Save label to master file")

if submitted and candidate_paths:
    rel_path = normalize_rel_path(rel_path)
    existing = labels_df[labels_df["rel_path"] == rel_path]
    if not existing.empty and not overwrite:
        st.error("This PDF already has a label. Enable overwrite to replace it.")
    else:
        inventory_match = inventory_df[inventory_df["rel_path"] == rel_path]
        doc_id_at_label_time = ""
        sha_at_label_time = ""
        if not inventory_match.empty:
            row = inventory_match.iloc[0]
            doc_id_at_label_time = _compute_doc_id_from_row(row)
            hash_value = row.get("hash_value")
            if isinstance(hash_value, str) and len(hash_value) == 64:
                sha_at_label_time = hash_value

        label_record = {
            "rel_path": rel_path,
            "label": str(label_value).upper(),
            "labeled_at": datetime.now(timezone.utc).isoformat(),
            "source_inventory_run": inventory_id,
            "source_probe_run": source_probe_run.strip(),
            "doc_id_at_label_time": doc_id_at_label_time,
            "sha256_at_label_time": sha_at_label_time,
            "notes": notes.strip(),
            "labeling_version": labeling_version.strip(),
        }

        labels_df = labels_df[labels_df["rel_path"] != rel_path]
        labels_df = pd.concat([labels_df, pd.DataFrame([label_record])], ignore_index=True)
        labels_df = normalize_labels_for_save(labels_df)
        write_labels(labels_df, labels_csv)
        match_result = match_labels_to_inventory(inventory_df, labels_df)
        reconcile_labels(
            inventory_df=inventory_df,
            labels_df=labels_df,
            outputs_root=out_dir,
            inventory_id=inventory_id,
            match_result=match_result,
        )
        st.success("Label saved to the master file.")

st.markdown("### 3) Review progress")
st.caption("Use these counts to track how much of the inventory has been labeled.")

match_result = match_labels_to_inventory(inventory_df, labels_df)
metric_cols = st.columns(3)
metric_cols[0].metric("Labeled PDFs", f"{len(match_result.matched):,}")
metric_cols[1].metric("Unlabeled PDFs", f"{len(match_result.unmatched_inventory):,}")
metric_cols[2].metric("Orphaned labels", f"{len(match_result.orphaned):,}")

st.markdown("### 4) Download or inspect the master labels file")
st.caption(
    "This CSV is the source of truth for labels. Share it with your team or keep it for audits and model training."
)

download_data = labels_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download master labels CSV",
    data=download_data,
    file_name="pdf_type_labels.csv",
    mime="text/csv",
)
st.code(str(labels_csv), language="text")

tabs = st.tabs(["Unlabeled PDFs", "Current labels", "Orphaned labels"])
with tabs[0]:
    unlabeled = match_result.unmatched_inventory.copy()
    if unlabeled.empty:
        st.info("All PDFs are labeled for this inventory.")
    else:
        st.dataframe(
            unlabeled[["rel_path", "top_level_folder", "extension"]]
            if "top_level_folder" in unlabeled.columns
            else unlabeled[["rel_path", "extension"]],
            use_container_width=True,
        )

with tabs[1]:
    if match_result.matched.empty:
        st.info("No labels have been matched to this inventory yet.")
    else:
        st.dataframe(
            match_result.matched[["rel_path", "label", "labeled_at", "notes"]]
            if "notes" in match_result.matched.columns
            else match_result.matched[["rel_path", "label", "labeled_at"]],
            use_container_width=True,
        )

with tabs[2]:
    if match_result.orphaned.empty:
        st.info("No orphaned labels detected.")
    else:
        st.dataframe(
            match_result.orphaned[["rel_path", "label", "labeled_at", "notes"]]
            if "notes" in match_result.orphaned.columns
            else match_result.orphaned[["rel_path", "label", "labeled_at"]],
            use_container_width=True,
        )
