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

from src.doj_doc_explorer.utils.fitz_loader import load_fitz_optional  # noqa: E402
from src.io_utils import get_default_out_dir  # noqa: E402
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.text_scan_io import load_latest_text_scan  # noqa: E402

st.set_page_config(page_title="Text Based Documents", layout="wide")

@st.cache_data(show_spinner=False)
def cached_list_probe_runs(out_dir_str: str) -> List[Dict]:
    return list_probe_runs(out_dir_str)


@st.cache_data(show_spinner=False)
def cached_load_probe_run(out_dir_str: str, run_id: str):
    return load_probe_run(out_dir_str, run_id)


@st.cache_data(show_spinner=False)
def cached_load_latest_text_scan(out_dir_str: str):
    return load_latest_text_scan(out_dir_str)


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
    fitz = load_fitz_optional()
    if not fitz:
        return False
    try:
        doc = fitz.open(path)
    except Exception:
        return False
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


def _normalize_rel_path(path: str) -> str:
    if not path:
        return ""
    cleaned = str(path).strip().replace("\\", "/")
    if "::" in cleaned:
        prefix, suffix = cleaned.split("::", 1)
        return f"{_normalize_segment(prefix)}::{_normalize_segment(suffix)}"
    return _normalize_segment(cleaned)


def _normalize_segment(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    while cleaned.startswith("/"):
        cleaned = cleaned[1:]
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    return "/".join(parts)


def _ensure_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df[columns]


def _bar_chart(df: pd.DataFrame) -> None:
    if df.empty or "content_type_pred" not in df.columns:
        st.info("No content type predictions available yet.")
        return
    counts = (
        df["content_type_pred"]
        .fillna("UNKNOWN")
        .value_counts()
        .reset_index()
    )
    counts.columns = ["Content type", "Documents"]
    fig = px.bar(
        counts,
        x="Content type",
        y="Documents",
        text="Documents",
        title="Content type mix for verified text PDFs",
        color="Content type",
    )
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title("Text Based Documents")
    st.caption(
        "Review documents that are already 100% text-based. This view stays local and does not send files "
        "anywhere, so you can safely share the screen with non-technical reviewers."
    )
    st.markdown(
        """
        **Why this matters:** text-based PDFs can be searched and summarized immediately, but some PDFs
        contain *empty or junk* text layers that look “text-ready” when they are not. This page now focuses
        exclusively on **verified text** (GOOD) documents. Suspicious text layers have moved to the
        **PDF Labeling** page so reviewers can relabel them in the same workflow.
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

    docs_df["rel_path_norm"] = docs_df["rel_path"].astype(str).map(_normalize_rel_path)
    text_scan_df, _text_scan_summary, _text_scan_run_log = cached_load_latest_text_scan(out_dir_text)
    if text_scan_df.empty:
        st.warning("No text scan runs found yet. This page will show probe-only results.")
    else:
        text_scan_df = text_scan_df.copy()
        text_scan_df["rel_path_norm"] = text_scan_df["rel_path"].astype(str).map(_normalize_rel_path)
        merge_cols = [
            "text_quality_label",
            "text_quality_score",
            "content_type_pred",
            "content_type_confidence",
            "total_words",
            "alpha_ratio",
            "gibberish_score",
            "avg_chars_per_text_page",
            "text_snippet",
        ]
        available_cols = [col for col in merge_cols if col in text_scan_df.columns and col not in docs_df.columns]
        if available_cols:
            docs_df = docs_df.merge(
                text_scan_df[available_cols + ["rel_path_norm"]],
                on="rel_path_norm",
                how="left",
            )

    text_docs_df = docs_df[docs_df["classification"] == "Text-based"].copy()
    if "text_quality_label" not in text_docs_df.columns:
        text_docs_df["text_quality_label"] = ""
    else:
        text_docs_df["text_quality_label"] = text_docs_df["text_quality_label"].fillna("").astype(str)
    text_docs_df["doc_label"] = text_docs_df.apply(_build_doc_label, axis=1)
    text_docs_df = text_docs_df.sort_values("doc_label")

    verified_df = text_docs_df[text_docs_df["text_quality_label"] == "GOOD"].copy()
    st.markdown("### Text scan overview")
    metric_cols = st.columns(2)
    metric_cols[0].metric("Probe text-based docs", f"{len(text_docs_df):,}")
    metric_cols[1].metric("Verified text (GOOD)", f"{len(verified_df):,}")

    st.markdown("### Content type mix (verified text)")
    _bar_chart(verified_df)

    st.markdown(
        """
        **How to use this page:** review the **Verified Text** list to confirm documents that are truly
        text-ready. For PDFs with suspicious or missing text layers, use the **PDF Labeling** page to
        relabel them as **IMAGE_OF_TEXT_PDF** or other appropriate types.
        """
    )

    if text_docs_df.empty:
        st.info(
            "No documents in the latest probe run are text-based yet. "
            "Run OCR or wait for more text-ready files, then refresh this page."
        )
        st.stop()

    if verified_df.empty:
        st.info(
            "No verified text (GOOD) PDFs were found in the latest text scan. "
            "Use the PDF Labeling page to triage suspicious or unscanned documents."
        )
        st.stop()

    tabs = st.tabs(["Verified Text (GOOD)"])
    search_value = st.text_input("Search relative path", value="")
    filtered_df = verified_df
    if search_value:
        mask = verified_df["rel_path"].str.contains(search_value, case=False, na=False)
        filtered_df = verified_df.loc[mask]
        if filtered_df.empty:
            st.warning("No text-based documents matched that relative path search.")
            st.stop()

    with tabs[0]:
        st.markdown("#### Verified text PDFs")
        st.dataframe(
            _ensure_columns(verified_df, ["rel_path", "page_count", "content_type_pred", "text_quality_score"]),
            use_container_width=True,
        )

    st.markdown("### Document preview")
    selected_label = st.selectbox(
        "Text-based document to preview",
        filtered_df["doc_label"].tolist(),
    )
    selected_row = verified_df.loc[verified_df["doc_label"] == selected_label].iloc[0]

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
        st.markdown("#### Signals")
        signal_cols = st.columns(2)
        signal_cols[0].metric("Text quality", str(selected_row.get("text_quality_label") or "Unknown"))
        signal_cols[1].metric("Quality score", f"{float(selected_row.get('text_quality_score') or 0):.2f}")
        st.caption(
            f"Content type: {selected_row.get('content_type_pred') or 'Unknown'} "
            f"(confidence {float(selected_row.get('content_type_confidence') or 0):.2f})"
        )
        st.markdown(
            f"""
            - **Total words:** {int(pd.to_numeric(selected_row.get("total_words"), errors="coerce") or 0)}
            - **Alpha ratio:** {float(selected_row.get("alpha_ratio") or 0):.2f}
            - **Gibberish score:** {float(selected_row.get("gibberish_score") or 0):.2f}
            """
        )

        show_snippet = False
        if isinstance(selected_row.get("text_snippet"), str) and selected_row.get("text_snippet"):
            show_snippet = st.checkbox("Show stored snippet (sanitized)", value=False)
        if show_snippet:
            st.text_area("Snippet", selected_row.get("text_snippet") or "", height=140)

        st.markdown("#### Optional extracted text preview")
        st.caption("This preview is generated live from your local PDF. It is hidden by default.")
        if st.checkbox("Show extracted text preview", value=False):
            with st.spinner("Extracting text..."):
                mtime = pdf_path.stat().st_mtime
                extracted_text, error = cached_extract_text(str(pdf_path), mtime, int(max_pages))
            if error:
                st.warning(error)
            else:
                st.text_area("", extracted_text, height=500)
                st.download_button(
                    "Download extracted text",
                    data=extracted_text.encode("utf-8"),
                    file_name=f"{pdf_path.stem}_extracted.txt",
                    mime="text/plain",
                )


if __name__ == "__main__":
    main()
