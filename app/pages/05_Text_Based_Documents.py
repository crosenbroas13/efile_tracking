import base64
import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.io_utils import get_default_out_dir  # noqa: E402
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402

st.set_page_config(page_title="Text Based Documents", layout="wide")

@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> List[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


@st.cache_data(show_spinner=False)
def cached_extract_text(path_str: str, mtime: float, max_pages: int) -> Tuple[str, Optional[str]]:
    if not importlib.util.find_spec("pypdf"):
        return "", "Install pypdf to enable text extraction in this view."
    PdfReader = importlib.import_module("pypdf").PdfReader
    path = Path(path_str)
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return "", f"Could not read PDF: {exc}"

    pages = reader.pages
    if max_pages > 0:
        pages = pages[:max_pages]

    chunks: List[str] = []
    for idx, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        header = f"--- Page {idx} ---"
        body = text.strip()
        if body:
            chunks.append(f"{header}\n{body}")
        else:
            chunks.append(f"{header}\n(no text extracted)")

    full_text = "\n\n".join(chunks).strip()
    return full_text, None


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
    page_count = int(pd.to_numeric(row.get("page_count"), errors="coerce") or 0)
    return f"{rel_path} · {page_count} pages"


def _pie_chart(text_count: int, other_count: int) -> None:
    pie_df = pd.DataFrame(
        {
            "Category": ["100% text-based", "Mixed or no text"],
            "Documents": [text_count, other_count],
        }
    )
    fig = px.pie(
        pie_df,
        names="Category",
        values="Documents",
        color="Category",
        color_discrete_map={
            "100% text-based": "#1f77b4",
            "Mixed or no text": "#C9CDD3",
        },
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title("Text Based Documents")
    st.caption(
        "Review documents that are already 100% text-based. This view stays local and does not send files "
        "anywhere, so you can safely share the screen with non-technical reviewers."
    )
    st.markdown(
        """
        **Why this matters:** text-based PDFs can be searched and summarized immediately, so this page isolates
        the documents that are ready for fast analysis. The chart below shows how much of your latest probe
        output falls into that fully text-based category.
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
    docs_df["text_coverage_pct"] = (
        pd.to_numeric(docs_df.get("text_coverage_pct"), errors="coerce").fillna(0)
    )

    total_docs = len(docs_df)
    text_docs_df = docs_df[docs_df["text_coverage_pct"] >= 1.0].copy()
    text_docs_df["doc_label"] = text_docs_df.apply(_build_doc_label, axis=1)
    text_docs_df = text_docs_df.sort_values("doc_label")
    other_docs = max(total_docs - len(text_docs_df), 0)

    st.markdown("### Latest probe coverage")
    metric_cols = st.columns(2)
    metric_cols[0].metric("100% text-based docs", f"{len(text_docs_df):,}")
    metric_cols[1].metric("Mixed or no-text docs", f"{other_docs:,}")
    _pie_chart(len(text_docs_df), other_docs)

    st.markdown(
        """
        **Next step:** pick a document to see the PDF (left) and the extracted text (right). The text shown
        here is extracted live from your local PDF file, so if the PDF has been moved or renamed you may see
        a warning instead of the preview.
        """
    )

    if text_docs_df.empty:
        st.info(
            "No documents in the latest probe run are 100% text-based yet. "
            "Run OCR or wait for more text-ready files, then refresh this page."
        )
        st.stop()

    search_value = st.text_input("Search relative path", value="")
    filtered_df = text_docs_df
    if search_value:
        mask = text_docs_df["rel_path"].str.contains(search_value, case=False, na=False)
        filtered_df = text_docs_df.loc[mask]
        if filtered_df.empty:
            st.warning("No text-based documents matched that relative path search.")
            st.stop()

    selected_label = st.selectbox(
        "Text-based document to preview",
        filtered_df["doc_label"].tolist(),
    )
    selected_row = text_docs_df.loc[text_docs_df["doc_label"] == selected_label].iloc[0]

    if isinstance(run_log, dict):
        output_root = run_log.get("output_root") or out_dir_text
    else:
        output_root = out_dir_text
    abs_path = str(selected_row.get("abs_path") or "")
    pdf_path = _resolve_pdf_path(abs_path, output_root)

    if not pdf_path or not pdf_path.exists():
        st.warning(
            "The PDF preview could not be found on disk. If this document lives inside a ZIP archive, "
            "rerun the probe to extract it or confirm the output folder matches the probe run."
        )
        st.stop()

    max_pages = st.number_input(
        "Max pages to extract (0 = all)",
        min_value=0,
        max_value=500,
        value=0,
        step=1,
        help="Limit extraction for very large PDFs to keep the page responsive.",
    )

    preview_cols = st.columns(2)
    with preview_cols[0]:
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
            key="text_doc_preview_mode",
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

    with preview_cols[1]:
        st.markdown("#### Extracted text")
        with st.spinner("Extracting text..."):
            mtime = pdf_path.stat().st_mtime
            extracted_text, error = cached_extract_text(str(pdf_path), mtime, int(max_pages))
        if error:
            st.warning(error)
        else:
            st.text_area("", extracted_text, height=800)
            st.download_button(
                "Download extracted text",
                data=extracted_text.encode("utf-8"),
                file_name=f"{pdf_path.stem}_extracted.txt",
                mime="text/plain",
            )


if __name__ == "__main__":
    main()
