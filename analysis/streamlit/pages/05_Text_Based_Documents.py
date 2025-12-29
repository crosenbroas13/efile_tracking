import base64
import hashlib
import importlib
import importlib.util
import re
import sys
from html import escape
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.doj_doc_explorer.utils.fitz_loader import load_fitz_optional  # noqa: E402
from src.probe_io import list_probe_runs, load_probe_run  # noqa: E402
from src.streamlit_config import get_output_dir  # noqa: E402
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


@st.cache_data(show_spinner=False)
def cached_search_keyword(
    path_str: str,
    mtime: float,
    keyword: str,
    case_sensitive: bool,
    max_pages: int,
) -> Tuple[List[Dict[str, object]], Optional[str]]:
    if not keyword:
        return [], None

    fitz = load_fitz_optional()
    pages: List[Dict[str, object]] = []
    if fitz:
        flags = 0
        if not case_sensitive and hasattr(fitz, "TEXT_IGNORECASE"):
            flags |= fitz.TEXT_IGNORECASE
        if hasattr(fitz, "TEXT_DEHYPHENATE"):
            flags |= fitz.TEXT_DEHYPHENATE
        try:
            doc = fitz.open(path_str)
        except Exception as exc:
            return [], f"Could not read PDF: {exc}"
        try:
            for page_index in range(doc.page_count):
                if max_pages > 0 and page_index >= max_pages:
                    break
                page = doc.load_page(page_index)
                text = page.get_text("text") or ""
                flags_for_regex = 0 if case_sensitive else re.IGNORECASE
                match_count = len(re.findall(re.escape(keyword), text, flags=flags_for_regex))
                if match_count:
                    pages.append(
                        {
                            "page_number": page_index + 1,
                            "match_count": match_count,
                            "text": text,
                        }
                    )
        finally:
            doc.close()
        return pages, None

    if not importlib.util.find_spec("pypdf"):
        return [], "Install PyMuPDF (fitz) or pypdf to enable keyword search."

    PdfReader = importlib.import_module("pypdf").PdfReader
    try:
        reader = PdfReader(path_str)
    except Exception as exc:
        return [], f"Could not read PDF: {exc}"

    flags_for_regex = 0 if case_sensitive else re.IGNORECASE
    for page_index, page in enumerate(reader.pages):
        if max_pages > 0 and page_index >= max_pages:
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        match_count = len(re.findall(re.escape(keyword), text, flags=flags_for_regex))
        if match_count:
            pages.append(
                {
                    "page_number": page_index + 1,
                    "match_count": match_count,
                    "text": text,
                }
            )

    return pages, None


def _highlight_keyword_text(text: str, keyword: str, case_sensitive: bool) -> str:
    if not text:
        return ""
    safe_text = escape(text)
    safe_keyword = escape(keyword)
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(safe_keyword), flags=flags)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", safe_text)


def _render_keyword_highlights(
    path: Path,
    keyword: str,
    case_sensitive: bool,
    max_pages: int,
    max_pages_with_hits: int,
) -> None:
    fitz = load_fitz_optional()
    if not fitz:
        st.warning("Install PyMuPDF (fitz) to render highlighted pages for keyword matches.")
        return

    flags = 0
    if not case_sensitive and hasattr(fitz, "TEXT_IGNORECASE"):
        flags |= fitz.TEXT_IGNORECASE
    if hasattr(fitz, "TEXT_DEHYPHENATE"):
        flags |= fitz.TEXT_DEHYPHENATE

    try:
        doc = fitz.open(path)
    except Exception as exc:
        st.warning(f"Could not read PDF for highlights: {exc}")
        return

    try:
        pages_shown = 0
        for page_index in range(doc.page_count):
            if max_pages > 0 and page_index >= max_pages:
                break
            page = doc.load_page(page_index)
            rects = page.search_for(keyword, flags=flags)
            if not rects:
                continue
            for rect in rects:
                page.add_highlight_annot(rect)
            pix = page.get_pixmap()
            st.image(
                pix.tobytes("png"),
                caption=f"Page {page_index + 1} ({len(rects)} matches)",
            )
            pages_shown += 1
            if max_pages_with_hits and pages_shown >= max_pages_with_hits:
                break
        if pages_shown == 0:
            st.info("No highlighted pages were found for this keyword.")
    finally:
        doc.close()


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
    counts.columns = ["Context type", "Documents"]
    fig = px.bar(
        counts,
        x="Context type",
        y="Documents",
        text="Documents",
        title="Context type mix for verified text documents",
        color="Context type",
    )
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title("Text Based Documents")
    st.caption(
        "Review documents that are already verified as GOOD text quality. This view stays local and does "
        "not send files anywhere, so you can safely share the screen with non-technical reviewers."
    )
    st.markdown(
        """
        **Why this matters:** text-based PDFs can be searched and summarized immediately, but some PDFs
        contain *empty or junk* text layers that look “text-ready” when they are not. This page now
        **shows only verified GOOD text quality documents**, so reviewers see what is ready for immediate
        search without wading through false positives.
        """
    )

    pick_cols = st.columns([2, 3])
    out_dir = get_output_dir()
    with pick_cols[0]:
        st.caption("Output folder (from Configuration page)")
        st.code(str(out_dir), language="text")
        st.page_link("pages/00_Configuration.py", label="Update output folder", icon="🧭")
    runs = cached_list_probe_runs(str(out_dir))
    if not runs:
        st.warning("No probe runs detected under this output folder yet.")
        st.stop()

    latest_run = runs[0]
    pick_cols[1].markdown("**Latest probe run**")
    pick_cols[1].markdown(_format_run_option(latest_run))

    docs_df, _pages_df, _summary, run_log = cached_load_probe_run(str(out_dir), latest_run["probe_run_id"])
    if docs_df.empty:
        st.warning("No document records found in this probe run.")
        st.stop()

    docs_df = docs_df.fillna("")
    docs_df["text_coverage_pct"] = (
        pd.to_numeric(docs_df.get("text_coverage_pct"), errors="coerce").fillna(0)
    )

    docs_df["rel_path_norm"] = docs_df["rel_path"].astype(str).map(_normalize_rel_path)
    text_scan_df, _text_scan_summary, _text_scan_run_log = cached_load_latest_text_scan(str(out_dir))
    if text_scan_df.empty:
        st.warning("No text scan runs found yet. Run a text scan to verify GOOD text quality.")
        st.stop()

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
    text_docs_df["text_quality_label"] = text_docs_df.get("text_quality_label", "").fillna("").astype(str)
    text_docs_df["text_quality_score"] = pd.to_numeric(
        text_docs_df.get("text_quality_score"), errors="coerce"
    ).fillna(0.0)
    text_docs_df["page_count"] = pd.to_numeric(text_docs_df.get("page_count"), errors="coerce").fillna(0).astype(int)
    text_docs_df["doc_label"] = text_docs_df.apply(_build_doc_label, axis=1)
    text_docs_df = text_docs_df.sort_values("doc_label")

    verified_df = text_docs_df[text_docs_df["text_quality_label"] == "GOOD"].copy()
    total_docs = len(docs_df)
    verified_pct = (len(verified_df) / total_docs * 100) if total_docs else 0.0

    st.markdown("### Verified text overview")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Verified text (GOOD)", f"{len(verified_df):,}")
    metric_cols[1].metric("Total documents in inventory", f"{total_docs:,}")
    metric_cols[2].metric("Share of inventory", f"{verified_pct:.1f}%")
    st.caption(
        f"Verified text documents represent **{verified_pct:.1f}%** of the current inventory, "
        "so reviewers can size the immediate search-ready workload."
    )

    st.markdown("### Context type mix (verified text)")
    _bar_chart(verified_df)

    if verified_df.empty:
        st.info(
            "No verified GOOD text documents were found. Run a text scan or improve text quality, then refresh."
        )
        st.stop()

    st.markdown("### Filtered download (verified text only)")
    filter_cols = st.columns(3)
    content_types = sorted(verified_df["content_type_pred"].fillna("UNKNOWN").unique().tolist())
    selected_types = filter_cols[0].multiselect(
        "Content type",
        options=content_types,
        default=content_types,
        help="Limit the export to specific content/context types.",
    )
    page_min, page_max = int(verified_df["page_count"].min()), int(verified_df["page_count"].max())
    selected_page_range = filter_cols[1].slider(
        "Page count range",
        min_value=page_min,
        max_value=max(page_max, page_min),
        value=(page_min, max(page_max, page_min)),
        help="Choose the page range for the table and download.",
    )
    score_min, score_max = float(verified_df["text_quality_score"].min()), float(verified_df["text_quality_score"].max())
    selected_score_range = filter_cols[2].slider(
        "Text quality score range",
        min_value=float(f"{score_min:.2f}"),
        max_value=float(f"{score_max:.2f}"),
        value=(float(f"{score_min:.2f}"), float(f"{score_max:.2f}")),
        help="Narrow to higher or lower text quality scores.",
    )

    filtered_df = verified_df.copy()
    if selected_types:
        filtered_df = filtered_df[filtered_df["content_type_pred"].fillna("UNKNOWN").isin(selected_types)]
    filtered_df = filtered_df[
        filtered_df["page_count"].between(selected_page_range[0], selected_page_range[1])
        & filtered_df["text_quality_score"].between(selected_score_range[0], selected_score_range[1])
    ]
    if filtered_df.empty:
        st.warning("No verified text documents match the selected filters.")
        st.stop()

    st.dataframe(
        _ensure_columns(
            filtered_df,
            ["rel_path", "page_count", "content_type_pred", "text_quality_score", "text_quality_label"],
        ),
        use_container_width=True,
    )
    download_bytes = filtered_df[
        ["rel_path", "page_count", "content_type_pred", "text_quality_score", "text_quality_label"]
    ].to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered verified text table",
        data=download_bytes,
        file_name="verified_text_documents.csv",
        mime="text/csv",
    )

    if isinstance(run_log, dict):
        output_root = run_log.get("output_root") or str(out_dir)
    else:
        output_root = str(out_dir)

    st.markdown("### Keyword search (verified text only)")
    st.caption(
        "Search across the filtered, verified text documents. Matches list the documents that contain "
        "your keyword so reviewers can click through, see a Chrome-safe preview, and confirm highlights "
        "directly in the text."
    )
    keyword_cols = st.columns([2, 1, 1])
    keyword = keyword_cols[0].text_input("Keyword", value="")
    keyword_case_sensitive = keyword_cols[1].checkbox("Case sensitive", value=False)
    keyword_max_pages = keyword_cols[2].number_input(
        "Max pages to scan (0 = all)",
        min_value=0,
        max_value=500,
        value=50,
        step=1,
        help="Limit the scan for very large PDFs to keep the search responsive.",
    )

    keyword_results: List[Dict[str, object]] = []
    missing_docs: List[str] = []
    if keyword:
        with st.spinner("Searching documents for keyword matches..."):
            for _, row in filtered_df.iterrows():
                abs_path = str(row.get("abs_path") or "")
                pdf_path = _resolve_pdf_path(abs_path, output_root)
                if not pdf_path or not pdf_path.exists():
                    missing_docs.append(str(row.get("rel_path") or "Unknown path"))
                    continue
                pages, error = cached_search_keyword(
                    str(pdf_path),
                    pdf_path.stat().st_mtime,
                    keyword,
                    keyword_case_sensitive,
                    int(keyword_max_pages),
                )
                if error:
                    st.warning(error)
                    break
                if pages:
                    keyword_results.append(
                        {
                            "rel_path": row.get("rel_path") or "",
                            "doc_label": row.get("doc_label") or row.get("rel_path") or "",
                            "page_count": int(row.get("page_count") or 0),
                            "abs_path": abs_path,
                            "match_pages": pages,
                            "match_count": sum(page["match_count"] for page in pages),
                        }
                    )

    if keyword and missing_docs:
        st.caption(
            "Some files were skipped because they could not be found on disk: "
            + ", ".join(missing_docs[:5])
            + ("..." if len(missing_docs) > 5 else "")
        )

    if keyword:
        if not keyword_results:
            st.info("No keyword matches were found in the current filtered list.")
        else:
            results_df = pd.DataFrame(
                [
                    {
                        "rel_path": result["rel_path"],
                        "page_count": result["page_count"],
                        "matches": result["match_count"],
                        "pages_with_matches": ", ".join(
                            str(page["page_number"]) for page in result["match_pages"]
                        ),
                    }
                    for result in keyword_results
                ]
            )
            st.dataframe(results_df, use_container_width=True)

            selected_keyword_doc = st.selectbox(
                "Keyword match to preview",
                [result["doc_label"] for result in keyword_results],
            )
            selected_keyword = next(
                result for result in keyword_results if result["doc_label"] == selected_keyword_doc
            )
            selected_keyword_path = _resolve_pdf_path(selected_keyword["abs_path"], output_root)

            st.markdown("#### Keyword preview (Chrome-safe)")
            preview_limit_cols = st.columns(2)
            highlight_page_limit = preview_limit_cols[0].number_input(
                "Max highlighted pages to render",
                min_value=1,
                max_value=25,
                value=5,
                step=1,
                help="Only pages with matches are rendered.",
            )
            extracted_page_limit = preview_limit_cols[1].number_input(
                "Max matched pages to show text for",
                min_value=1,
                max_value=50,
                value=min(10, len(selected_keyword["match_pages"])),
                step=1,
            )

            if selected_keyword_path and selected_keyword_path.exists():
                _render_keyword_highlights(
                    selected_keyword_path,
                    keyword,
                    keyword_case_sensitive,
                    int(keyword_max_pages),
                    int(highlight_page_limit),
                )
                st.markdown("#### Extracted text with highlights")
                st.caption(
                    "Highlighted text is extracted locally and shown only for pages that contain matches."
                )
                for page in selected_keyword["match_pages"][: int(extracted_page_limit)]:
                    st.markdown(f"**Page {page['page_number']}**")
                    highlighted = _highlight_keyword_text(
                        str(page.get("text") or ""),
                        keyword,
                        keyword_case_sensitive,
                    )
                    st.markdown(f"<div>{highlighted}</div>", unsafe_allow_html=True)
            else:
                st.warning("The selected document could not be found on disk for preview.")

    st.markdown("### Document preview")
    selected_label = st.selectbox(
        "Verified text document to preview",
        filtered_df["doc_label"].tolist(),
    )
    selected_row = verified_df.loc[verified_df["doc_label"] == selected_label].iloc[0]

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
