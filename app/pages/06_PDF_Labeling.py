import hashlib
import importlib.util
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, Optional

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
    normalize_label_value,
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
from src.probe_io import list_probe_runs, load_probe_run

st.set_page_config(page_title="PDF Labeling", layout="wide")

MAX_LABEL_PAGES = 5


@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> list[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


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


def _safe_zip_entry_path(entry_name: str) -> Path:
    entry = PurePosixPath(entry_name)
    parts = [part for part in entry.parts if part not in ("", ".", "..")]
    return Path(*parts) if parts else Path("entry.pdf")


def _zip_extract_dir(zip_path: Path, extract_root: Path) -> Path:
    digest = hashlib.sha256(str(zip_path).encode("utf-8")).hexdigest()[:8]
    return extract_root / f"{zip_path.stem}_{digest}"


def _split_zip_abs_path(abs_path: str) -> Optional[tuple[Path, str]]:
    if "::" not in abs_path:
        return None
    zip_part, entry_part = abs_path.split("::", 1)
    if not zip_part or not entry_part:
        return None
    return Path(zip_part), entry_part


def _resolve_pdf_path(abs_path: str, output_root: Optional[str]) -> Optional[Path]:
    if not abs_path:
        return None
    if "::" not in abs_path:
        return Path(abs_path)
    split = _split_zip_abs_path(abs_path)
    if not split:
        return None
    zip_path, entry_name = split
    if not output_root:
        return None
    extract_root = Path(output_root) / "probe_extracts"
    safe_entry = _safe_zip_entry_path(entry_name)
    return _zip_extract_dir(zip_path, extract_root) / safe_entry


def _render_pdf_image_preview(path: Path, max_pages: int = MAX_LABEL_PAGES) -> bool:
    if not importlib.util.find_spec("fitz"):
        return False
    fitz = importlib.import_module("fitz")
    doc = fitz.open(path)
    try:
        if doc.page_count < 1:
            return False
        pages_to_show = min(doc.page_count, max_pages)
        for page_index in range(pages_to_show):
            page = doc.load_page(page_index)
            pix = page.get_pixmap()
            st.image(pix.tobytes("png"), caption=f"Page {page_index + 1} of {doc.page_count}")
        if doc.page_count > pages_to_show:
            st.caption(
                f"Only the first {pages_to_show} pages are shown here to keep the review queue focused."
            )
        return True
    finally:
        doc.close()


def _merge_page_counts(inventory_df: pd.DataFrame, docs_df: pd.DataFrame) -> pd.DataFrame:
    if docs_df.empty or "rel_path" not in docs_df.columns:
        inventory_df = inventory_df.copy()
        inventory_df["page_count"] = pd.NA
        return inventory_df
    docs_view = docs_df.copy()
    docs_view["rel_path"] = docs_view["rel_path"].astype(str).map(normalize_rel_path)
    docs_view["page_count"] = pd.to_numeric(docs_view.get("page_count"), errors="coerce")
    return inventory_df.merge(docs_view[["rel_path", "page_count"]], on="rel_path", how="left")


def _add_folder_columns(inventory_df: pd.DataFrame) -> pd.DataFrame:
    inventory_df = inventory_df.copy()
    rel_paths = inventory_df["rel_path"].astype(str).map(normalize_rel_path)
    parent_folder = rel_paths.map(lambda path: PurePosixPath(path).parent.as_posix())
    inventory_df["parent_folder"] = parent_folder.replace({".": "Root"})
    if "top_level_folder" not in inventory_df.columns:
        inventory_df["top_level_folder"] = rel_paths.map(
            lambda path: PurePosixPath(path).parts[0] if PurePosixPath(path).parts else "Root"
        )
    inventory_df["top_level_folder"] = inventory_df["top_level_folder"].fillna("Root").replace("", "Root")
    return inventory_df


st.title("PDF Type Labeling")
st.caption("Friendly workspace for applying human-reviewed labels and saving them to the master labels file.")

st.markdown(
    """
    Use this page to confirm whether a PDF is **text-based**, **image-based**, or **mixed**.
    Every label you apply is written to a master CSV file that can be reused across reruns,
    so reviewers do not have to repeat work.
    """
)
st.markdown(
    """
    **Label guide (plain language)**
    - **TEXT_PDF**: real, selectable text (born-digital PDFs).
    - **IMAGE_OF_TEXT_PDF**: looks like text but is actually scanned images.
    - **IMAGE_PDF**: photos, scans, or forms that are not text-like.
    - **MIXED_PDF**: some pages have real text and others are scanned images.
    """
)
st.caption(
    "Note: labels are saved with both the original selection (label_raw) and a normalized label "
    "(label_norm) so legacy labels can be compared consistently across reruns."
)
st.markdown(
    f"""
    **Why the list is short:** this labeling queue only shows PDFs that are **{MAX_LABEL_PAGES} pages or fewer**.
    Short documents are faster to review and make a clean starter dataset for future ML training, so each label
    you apply here can become a high-quality example in the training repository.
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

probe_runs = cached_list_probe_runs(str(out_dir))
if not probe_runs:
    st.warning("No probe runs found. Run a probe so this page can filter PDFs by page count.")
    st.stop()

latest_probe = probe_runs[0]
docs_df, _pages_df, _summary, _run_log = cached_load_probe_run(str(out_dir), latest_probe["probe_run_id"])
if docs_df.empty or "page_count" not in docs_df.columns:
    st.warning("The latest probe run does not include page counts. Re-run the probe to continue.")
    st.stop()
st.caption(f"Latest probe run used for page counts: {latest_probe['probe_run_id']}")

labels_csv = labels_path(out_dir)
labels_df = load_labels(labels_csv, inventory_df)

st.markdown("### 2) Apply a label")
st.caption(
    "Pick a PDF, choose a label, and save it to the master file. Notes are optional but helpful. "
    f"This view only lists documents with {MAX_LABEL_PAGES} or fewer pages so each label can double as "
    "a compact ML training example."
)

st.markdown(
    """
    **Find the right PDF faster**

    Use these controls to keep the list manageable:
    - **Search** narrows the list by anything in the path (folder name or file name).
    - **Browse by folder** keeps similar PDFs together so you can label in batches.
    - **Sort order** changes which files appear first, so you can prioritize quick wins.
    """
)

inventory_ui = _merge_page_counts(inventory_df, docs_df)
inventory_ui["page_count"] = pd.to_numeric(inventory_ui["page_count"], errors="coerce").fillna(0)
inventory_ui = inventory_ui[
    (inventory_ui["page_count"] > 0) & (inventory_ui["page_count"] <= MAX_LABEL_PAGES)
].copy()
inventory_ui = _add_folder_columns(inventory_ui)
label_lookup = labels_df.set_index("rel_path")["label_norm"].to_dict() if not labels_df.empty else {}
inventory_ui["current_label"] = inventory_ui["rel_path"].map(label_lookup).fillna("")
inventory_ui["is_labeled"] = inventory_ui["current_label"].astype(str).str.strip() != ""

if inventory_ui.empty:
    st.warning(
        f"No PDFs under {MAX_LABEL_PAGES} pages were found in the latest probe run. "
        "Run a probe on the inventory or adjust the inventory selection."
    )
    st.stop()

show_labeled = st.checkbox(
    "Include already labeled PDFs",
    value=False,
    help="Turn this on only when you need to review or update existing labels.",
)

filter_cols = st.columns([2, 2, 2])
with filter_cols[0]:
    filter_text = st.text_input(
        "Search by folder or filename",
        value="",
        help="Type part of a path to narrow the list, especially for large inventories.",
    )
with filter_cols[1]:
    browse_mode = st.selectbox(
        "Browse by folder",
        options=["All folders", "Top-level folder", "Parent folder"],
        help="Switch to a folder view when you want to label similar files together.",
    )
with filter_cols[2]:
    sort_choice = st.selectbox(
        "Sort list by",
        options=[
            "Relative path (A → Z)",
            "Relative path (Z → A)",
            "Page count (short → long)",
            "Page count (long → short)",
            "File size (small → large)",
            "File size (large → small)",
        ],
        help="Sorting only affects the list order, not the saved labels.",
    )

candidate_df = inventory_ui if show_labeled else inventory_ui[~inventory_ui["is_labeled"]].copy()
if filter_text:
    candidate_df = candidate_df[candidate_df["rel_path"].str.contains(filter_text, case=False, na=False)]

if browse_mode != "All folders":
    folder_column = "top_level_folder" if browse_mode == "Top-level folder" else "parent_folder"
    folder_options = sorted(candidate_df[folder_column].dropna().astype(str).unique().tolist())
    selected_folder = st.selectbox(
        "Choose a folder",
        options=["All folders"] + folder_options,
        help="Selecting a folder filters the list below to just that folder.",
    )
    if selected_folder != "All folders":
        candidate_df = candidate_df[candidate_df[folder_column] == selected_folder]

sort_key_map = {
    "Relative path (A → Z)": ("rel_path", True),
    "Relative path (Z → A)": ("rel_path", False),
    "Page count (short → long)": ("page_count", True),
    "Page count (long → short)": ("page_count", False),
    "File size (small → large)": ("size_bytes", True),
    "File size (large → small)": ("size_bytes", False),
}
sort_column, sort_ascending = sort_key_map.get(sort_choice, ("rel_path", True))
if sort_column in candidate_df.columns:
    candidate_df = candidate_df.sort_values(sort_column, ascending=sort_ascending, kind="mergesort")
else:
    candidate_df = candidate_df.sort_values("rel_path", ascending=True, kind="mergesort")

candidate_paths = candidate_df["rel_path"].tolist()

def _format_candidate_option(value: str) -> str:
    page_count = candidate_df.loc[candidate_df["rel_path"] == value, "page_count"]
    page_count = int(page_count.iloc[0]) if not page_count.empty else 0
    return f"{value} · {page_count} pages"


selected_rel_path = st.selectbox(
    "PDF to label",
    options=candidate_paths or ["No matching PDFs found"],
    format_func=_format_candidate_option if candidate_paths else None,
    help="If the list is long, use the filter above to narrow it.",
)

detail_cols = st.columns([2, 3])
with detail_cols[0]:
    with st.form("apply_label"):
        label_value = st.selectbox("Label", options=sorted(LABEL_VALUES))
        notes = st.text_area(
            "Reviewer notes (optional)",
            help="Record anything that helps explain your choice later.",
        )
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

with detail_cols[1]:
    if candidate_paths:
        preview_row = candidate_df[candidate_df["rel_path"] == selected_rel_path].iloc[0]
        abs_path = str(preview_row.get("abs_path") or "")
        pdf_path = _resolve_pdf_path(abs_path, out_dir_text)
        st.markdown("#### Chrome-safe PDF preview (up to 5 pages)")
        if not pdf_path or not pdf_path.exists():
            st.warning("PDF file not found on disk. Confirm the inventory path is still valid.")
        else:
            rendered = _render_pdf_image_preview(pdf_path, MAX_LABEL_PAGES)
            if not rendered:
                st.info(
                    "Install PyMuPDF (`pip install pymupdf`) to render page images in the browser. "
                    "This keeps previews Chrome-safe while staying entirely local."
                )
                st.download_button(
                    "Download PDF",
                    data=pdf_path.read_bytes(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                )

if submitted and candidate_paths:
    rel_path = normalize_rel_path(selected_rel_path)
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
            "label_raw": str(label_value).upper(),
            "label_norm": normalize_label_value(label_value),
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
            match_result.matched[["rel_path", "label_norm", "labeled_at", "notes"]]
            if "notes" in match_result.matched.columns
            else match_result.matched[["rel_path", "label_norm", "labeled_at"]],
            use_container_width=True,
        )

with tabs[2]:
    if match_result.orphaned.empty:
        st.info("No orphaned labels detected.")
    else:
        st.dataframe(
            match_result.orphaned[["rel_path", "label_norm", "labeled_at", "notes"]]
            if "notes" in match_result.orphaned.columns
            else match_result.orphaned[["rel_path", "label_norm", "labeled_at"]],
            use_container_width=True,
        )
