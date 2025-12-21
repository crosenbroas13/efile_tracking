from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import importlib.util

import pandas as pd

_pypdf_spec = importlib.util.find_spec("pypdf")
if _pypdf_spec:
    from pypdf import PdfReader
else:  # pragma: no cover - optional dependency guard
    PdfReader = None

from src.probe_config import ProbeConfig

LOGGER = logging.getLogger(__name__)


def stable_doc_id(row: pd.Series) -> str:
    if pd.notna(row.get("sha256")) and row.get("sha256"):
        return str(row["sha256"])
    rel_path = str(row.get("rel_path", ""))
    size = int(row.get("size_bytes", 0))
    modified = str(row.get("modified_time", ""))
    return f"{rel_path}|{size}|{modified}"


def list_pdfs(
    inventory_path: Path, only_top_folder: Optional[str] = None
) -> tuple[pd.DataFrame, Dict[str, int], Dict[str, int]]:
    df = pd.read_csv(inventory_path)
    if only_top_folder:
        df = df[df.get("top_level_folder") == only_top_folder]

    df["extension"] = df["extension"].fillna("").str.lower()
    pdf_df = df[df["extension"] == "pdf"].copy()
    non_pdf_df = df[df["extension"] != "pdf"].copy()
    ignored_counts = non_pdf_df["extension"].value_counts(dropna=False).to_dict()
    mime_col = "detected_mime" if "detected_mime" in non_pdf_df.columns else None
    ignored_mime_counts: Dict[str, int] = {}
    if mime_col:
        ignored_mime_counts = non_pdf_df[mime_col].fillna("").value_counts(dropna=False).to_dict()

    pdf_df["doc_id"] = pdf_df.apply(stable_doc_id, axis=1)
    return pdf_df.reset_index(drop=True), ignored_counts, ignored_mime_counts


def classify_document(text_coverage_pct: float, config: ProbeConfig) -> str:
    if text_coverage_pct >= config.doc_text_pct_text:
        return "Text-based"
    if text_coverage_pct < config.doc_text_pct_scanned:
        return "Scanned"
    return "Mixed"


def _extract_page_text(page) -> str:
    try:
        text = page.extract_text() or ""
    except Exception:
        return ""
    return text


def _process_pdf_text(path: Path, config: ProbeConfig, max_pages: int = 0) -> Dict:
    if PdfReader is None:
        msg = "pypdf is not installed; text extraction skipped"
        LOGGER.warning(msg)
        return {"error": msg, "pages": [], "page_count": 0}
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # encryption or unreadable
        LOGGER.warning("Failed to open PDF %s: %s", path, exc)
        return {"error": str(exc), "pages": [], "page_count": 0}

    pages_data: List[Dict] = []
    page_total = len(reader.pages)
    pages_to_process = page_total if max_pages <= 0 else min(max_pages, page_total)

    for idx in range(pages_to_process):
        page = reader.pages[idx]
        text = _extract_page_text(page)
        text_char_count = len(text.strip())
        has_text = text_char_count >= config.text_char_threshold
        pages_data.append(
            {
                "page_num": idx + 1,
                "text_char_count": text_char_count,
                "has_text": has_text,
            }
        )
    return {"pages": pages_data, "page_count": pages_to_process}


def evaluate_readiness(
    pdfs: pd.DataFrame,
    config: ProbeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
    records: List[Dict] = []
    doc_records: List[Dict] = []
    errors: List[Dict] = []

    pdf_iterable: Iterable[pd.Series] = pdfs.itertuples(index=False)
    pdf_list = list(pdf_iterable)

    if config.seed is not None:
        random.seed(config.seed)
    if config.max_pdfs and config.max_pdfs > 0 and len(pdf_list) > config.max_pdfs:
        pdf_list = random.sample(pdf_list, config.max_pdfs)

    for row in pdf_list:
        row_dict = row._asdict()
        doc_id = row_dict["doc_id"]
        abs_path = Path(row_dict["abs_path"])
        text_result = {"pages": [], "page_count": 0}
        doc_errors: List[str] = []
        if not config.skip_text_check:
            text_result = _process_pdf_text(abs_path, config, max_pages=config.max_pages)
            if text_result.get("error"):
                doc_errors.append(text_result["error"])
        pages_info = text_result.get("pages", [])
        for page_data in pages_info:
            records.append(
                {
                    "doc_id": doc_id,
                    "rel_path": row_dict.get("rel_path"),
                    "abs_path": row_dict.get("abs_path"),
                    "top_level_folder": row_dict.get("top_level_folder"),
                    "page_num": page_data["page_num"],
                    "text_char_count": page_data["text_char_count"],
                    "has_text": page_data["has_text"],
                }
            )
        page_count = text_result.get("page_count", 0)
        pages_with_text = sum(1 for p in pages_info if p.get("has_text"))
        text_coverage_pct = (pages_with_text / page_count) if page_count else 0
        classification = classify_document(text_coverage_pct, config) if page_count else "Unknown"
        doc_records.append(
            {
                "doc_id": doc_id,
                "rel_path": row_dict.get("rel_path"),
                "abs_path": row_dict.get("abs_path"),
                "top_level_folder": row_dict.get("top_level_folder"),
                "page_count": page_count,
                "pages_with_text": pages_with_text,
                "text_coverage_pct": text_coverage_pct,
                "classification": classification,
                "notes": "; ".join(doc_errors) if doc_errors else "",
            }
        )
        if doc_errors:
            errors.append(
                {
                    "doc_id": doc_id,
                    "path": row_dict.get("abs_path"),
                    "errors": doc_errors,
                }
            )

    pages_df = pd.DataFrame(records)
    docs_df = pd.DataFrame(doc_records)
    return pages_df, docs_df, errors


__all__ = [
    "ProbeConfig",
    "list_pdfs",
    "classify_document",
    "evaluate_readiness",
    "stable_doc_id",
]
