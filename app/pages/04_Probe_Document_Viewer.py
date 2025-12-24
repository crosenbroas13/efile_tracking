import base64
import hashlib
import importlib.util
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.io_utils import get_default_out_dir  # noqa: E402
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402

st.set_page_config(page_title="Probe Document Viewer", layout="wide")

@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> List[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


def _format_run_option(run: Dict) -> str:
    ts = run.get("timestamp")
    ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "(time unknown)"
    summary = run.get("summary") or {}
    pdfs = summary.get("total_pdfs")
    extras = f"{pdfs} PDFs" if pdfs is not None else "no counts"
    return f"{run.get('probe_run_id')} – {ts_text} – {extras}"


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


def _render_pdf(path: Path) -> None:
    pdf_bytes = path.read_bytes()
    b64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
    iframe = (
        "<iframe src=\"data:application/pdf;base64," + b64_pdf +
        "\" width=\"100%\" height=\"800\" type=\"application/pdf\"></iframe>"
    )
    st.components.v1.html(iframe, height=820, scrolling=True)


def _render_pdf_image_preview(path: Path) -> bool:
    if not importlib.util.find_spec("fitz"):
        return False
    fitz = importlib.import_module("fitz")
    doc = fitz.open(path)
    try:
        if doc.page_count < 1:
            return False
        page = doc.load_page(0)
        pix = page.get_pixmap()
        st.image(pix.tobytes("png"), caption="Page 1 preview (rendered locally)")
        if doc.page_count > 1:
            st.caption("Only the first page is shown to keep the preview lightweight.")
        return True
    finally:
        doc.close()


def _build_doc_label(row: pd.Series) -> str:
    rel_path = str(row.get("rel_path") or "(unknown path)")
    classification = str(row.get("classification") or "Unknown")
    page_count = int(pd.to_numeric(row.get("page_count"), errors="coerce") or 0)
    return f"{rel_path} · {classification} · {page_count} pages"


def main() -> None:
    st.title("Probe Document Viewer")
    st.caption(
        "Review a single PDF from the latest probe run without leaving the dashboard. "
        "Files stay on your machine, and this page only reads already-saved probe outputs."
    )

    st.markdown(
        """
        **How it works:** this page looks for the most recent probe run in your output folder,
        then lets you pick one document to preview. The preview is generated locally so you can
        share quick findings with non-technical reviewers without running new probes.
        """
    )
    st.info(
        "Need an older run? Use the Probe QA page to review historical probes. "
        "This viewer stays locked to the latest run to keep the choice simple for reviewers."
    )
    st.markdown(
        """
        **Tip for document-specific reviews:** paste a relative path (the path shown in inventory outputs)
        in the search box below to jump straight to a specific file. The match is case-insensitive and
        finds partial matches, so you can search with just a folder name or a filename fragment. You can
        also share a link by adding `?rel_path=your/path.pdf` to the page URL.
        """
    )

    pick_cols = st.columns([2, 3])
    out_dir_text = pick_cols[0].text_input("Output folder", value=str(get_default_out_dir()))
    runs = cached_list_probe_runs(out_dir_text)
    if not runs:
        st.warning("No probe runs detected under this output folder yet.")
        st.stop()

    latest_run = runs[0]
    pick_cols[1].markdown("**Latest probe run**")
    pick_cols[1].markdown(_format_run_option(latest_run))

    docs_df, _pages_df, _summary, run_log = cached_load_probe_run(out_dir_text, latest_run["probe_run_id"])
    if docs_df.empty:
        st.warning("No document records found in this probe run.")
        st.stop()

    docs_df = docs_df.fillna("")
    docs_df["doc_label"] = docs_df.apply(_build_doc_label, axis=1)
    docs_df = docs_df.sort_values("doc_label")

    query_rel_path = st.query_params.get("rel_path", "")
    search_value = st.text_input("Search relative path", value=query_rel_path or "")
    if search_value:
        st.query_params["rel_path"] = search_value
    elif "rel_path" in st.query_params:
        del st.query_params["rel_path"]
    filtered_df = docs_df
    if search_value:
        mask = docs_df["rel_path"].str.contains(search_value, case=False, na=False)
        filtered_df = docs_df.loc[mask]
        if filtered_df.empty:
            st.warning("No documents matched that relative path search.")
            st.stop()
    selected_label = st.selectbox(
        "Document to preview",
        filtered_df["doc_label"].tolist(),
    )
    selected_row = docs_df.loc[docs_df["doc_label"] == selected_label].iloc[0]

    if isinstance(run_log, dict):
        output_root = run_log.get("output_root") or out_dir_text
    else:
        output_root = out_dir_text
    abs_path = str(selected_row.get("abs_path") or "")
    pdf_path = _resolve_pdf_path(abs_path, output_root)

    detail_cols = st.columns(3)
    detail_cols[0].metric("Classification", selected_row.get("classification") or "Unknown")
    detail_cols[1].metric("Pages", int(pd.to_numeric(selected_row.get("page_count"), errors="coerce") or 0))
    detail_cols[2].metric("Text coverage", f"{float(selected_row.get('text_coverage_pct') or 0):.0%}")

    st.markdown("#### Document metadata")
    st.code(f"Relative path: {selected_row.get('rel_path')}")
    st.code(f"Source path: {abs_path}")

    if not pdf_path or not pdf_path.exists():
        st.warning(
            "The PDF preview could not be found on disk. If this document lives inside a ZIP archive, "
            "rerun the probe to extract it or confirm the output folder matches the probe run."
        )
        st.stop()

    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 25:
        st.info(
            f"This file is {file_size_mb:.1f} MB. Large PDFs may take a moment to load in the preview."
        )

    st.download_button(
        "Download selected PDF",
        data=pdf_path.read_bytes(),
        file_name=pdf_path.name,
        mime="application/pdf",
    )

    st.markdown("#### PDF preview")
    st.caption(
        "If your browser blocks embedded PDFs, switch to the rendered image mode. "
        "It shows the first page only, keeping the preview lightweight for reviewers."
    )
    preview_mode = st.radio(
        "Preview mode",
        options=["Embedded PDF (may be blocked)", "Rendered image (Chrome-safe)"],
        horizontal=True,
        index=1,
    )
    if preview_mode.startswith("Rendered"):
        rendered = _render_pdf_image_preview(pdf_path)
        if not rendered:
            st.warning(
                "Image preview requires PyMuPDF (`fitz`). Install it to use this mode, "
                "or download the PDF to view it in a local reader."
            )
    else:
        _render_pdf(pdf_path)


if __name__ == "__main__":
    main()
