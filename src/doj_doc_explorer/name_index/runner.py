from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

import pandas as pd

from src.probe_readiness import list_pdfs

from ..utils.fitz_loader import load_fitz
from ..utils.io import load_table, read_json
from ..utils.paths import normalize_rel_path
from .config import NameIndexRunConfig
from .schema import (
    DocMetadata,
    NameIndexAccumulator,
    NormalizedName,
    build_public_records,
    is_all_caps_heading,
    normalize_person_name,
)
from .io import write_name_index_outputs


_NAME_TOKEN = r"[A-Z][A-Za-z]*(?:['’\-][A-Za-z]+)*"
_MIDDLE_INITIAL = r"[A-Z](?:\.)?"
_SUFFIX = r"(?:Jr|Sr|II|III)\.?"

_FIRST_LAST_RE = re.compile(
    rf"\b(?P<first>{_NAME_TOKEN})\s+(?:(?P<middle>{_MIDDLE_INITIAL})\s+)?(?P<last>{_NAME_TOKEN})(?:,?\s+(?P<suffix>{_SUFFIX}))?\b"
)
_LAST_FIRST_RE = re.compile(
    rf"\b(?P<last>{_NAME_TOKEN})\s*,\s*(?P<first>{_NAME_TOKEN})(?:\s+(?P<middle>{_MIDDLE_INITIAL}))?(?:\s+(?P<suffix>{_SUFFIX}))?\b"
)


def run_name_index(
    config: NameIndexRunConfig,
    *,
    probe_docs: pd.DataFrame | None = None,
    text_scan_df: pd.DataFrame | None = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    fitz = load_fitz()
    if probe_docs is None:
        probe_docs = load_table(config.probe_run_dir / "readiness_docs")
    if text_scan_df is None:
        text_scan_df = load_table(config.text_scan_run_dir / "doc_text_signals")

    if probe_docs.empty:
        raise SystemExit("Probe readiness_docs not found or empty; run probe first.")
    if text_scan_df.empty:
        raise SystemExit("Text scan outputs not found or empty; run text_scan first.")

    text_scan_summary = read_json(config.text_scan_run_dir / "text_scan_summary.json")
    text_scan_probe_id = text_scan_summary.get("probe_run_id")
    probe_run_id = config.probe_run_dir.name
    if text_scan_probe_id and text_scan_probe_id != probe_run_id:
        meta_warning = {
            "warning": "text_scan_probe_mismatch",
            "text_scan_probe_run_id": text_scan_probe_id,
            "probe_run_id": probe_run_id,
        }
    else:
        meta_warning = {}

    pdfs_df, _, _ = list_pdfs(config.inventory_path, extract_root=config.outputs_root)
    pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)
    probe_docs["rel_path"] = probe_docs["rel_path"].astype(str).map(normalize_rel_path)
    text_scan_df["rel_path"] = text_scan_df["rel_path"].astype(str).map(normalize_rel_path)

    text_scan_df = text_scan_df.drop_duplicates(subset=["rel_path"])
    merged = probe_docs.merge(
        text_scan_df[
            [
                "rel_path",
                "text_quality_label",
                "content_type_pred",
            ]
        ],
        on="rel_path",
        how="left",
    )
    if config.only_verified_good:
        merged = merged[merged["text_quality_label"] == "GOOD"].copy()

    if merged.empty:
        raise SystemExit("No verified GOOD text PDFs found; run text_scan first or adjust filters.")

    merged = merged.merge(
        pdfs_df[
            [
                "doc_id",
                "rel_path",
                "probe_path",
                "abs_path",
                "top_level_folder",
            ]
        ],
        on="rel_path",
        how="left",
        suffixes=("", "_inv"),
    )
    merged["doc_id"] = merged["doc_id"].fillna(merged.get("doc_id_inv"))
    merged["top_level_folder"] = merged["top_level_folder"].fillna(merged.get("top_level_folder_inv"))
    merged["scan_path"] = merged["probe_path"].fillna(merged["abs_path"])

    accumulator = NameIndexAccumulator()
    errors: List[Dict[str, str]] = []
    docs_scanned = 0
    docs_skipped = 0
    total_pages = 0

    for row in merged.itertuples(index=False):
        row_dict = row._asdict()
        rel_path = str(row_dict.get("rel_path") or "")
        doc_id = str(row_dict.get("doc_id") or "")
        scan_path = row_dict.get("scan_path")
        if not scan_path:
            errors.append({"rel_path": rel_path, "doc_id": doc_id, "error": "missing scan path"})
            docs_skipped += 1
            continue
        pdf_path = Path(str(scan_path))
        if not pdf_path.exists():
            errors.append({"rel_path": rel_path, "doc_id": doc_id, "error": f"missing file: {pdf_path}"})
            docs_skipped += 1
            continue

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as exc:
            errors.append({"rel_path": rel_path, "doc_id": doc_id, "error": f"pdf open error: {exc}"})
            docs_skipped += 1
            continue

        doc_meta = _build_doc_metadata(row_dict, doc.page_count)
        doc_mentions, exceeded = _collect_doc_mentions(
            doc=doc,
            max_names_per_doc=config.max_names_per_doc,
        )
        doc.close()
        if exceeded:
            errors.append(
                {
                    "rel_path": rel_path,
                    "doc_id": doc_id,
                    "error": f"exceeded max_names_per_doc={config.max_names_per_doc}",
                }
            )
            docs_skipped += 1
            continue

        for canonical_key, mention in doc_mentions.items():
            for page_num, count in mention["pages"].items():
                normalized = mention["normalized"]
                accumulator.add(normalized, doc_meta, page_num, count)

        docs_scanned += 1
        total_pages += doc.page_count

    records = accumulator.to_records(min_total_count=config.min_total_count)
    public_records = build_public_records(records)
    meta = {
        "docs_scanned": docs_scanned,
        "docs_skipped": docs_skipped,
        "total_pages_scanned": total_pages,
        "errors": errors,
        "error_count": len(errors),
        "total_names": accumulator.total_names(),
        "names_output": len(records),
        **meta_warning,
    }
    return records, public_records, meta


def run_name_index_and_save(
    config: NameIndexRunConfig,
    *,
    probe_docs: pd.DataFrame | None = None,
    text_scan_df: pd.DataFrame | None = None,
) -> Path:
    records, public_records, meta = run_name_index(config, probe_docs=probe_docs, text_scan_df=text_scan_df)
    return write_name_index_outputs(records, public_records, config, meta)


def run_name_index_and_save_for_probe(
    config: NameIndexRunConfig,
    *,
    probe_docs: pd.DataFrame,
    text_scan_df: pd.DataFrame,
) -> Tuple[Path, Dict[str, object]]:
    records, public_records, meta = run_name_index(config, probe_docs=probe_docs, text_scan_df=text_scan_df)
    run_dir = write_name_index_outputs(records, public_records, config, meta)
    return run_dir, meta


def _build_doc_metadata(row: Dict[str, object], page_count: int) -> DocMetadata:
    doc_id = str(row.get("doc_id") or "")
    rel_path = str(row.get("rel_path") or "")
    top_level_folder = str(row.get("top_level_folder") or "")
    doc_type_final = row.get("doc_type_final")
    content_type = row.get("content_type_pred")
    doj_url = row.get("doj_url") or row.get("source_url") or row.get("download_url")
    title = row.get("title") or Path(rel_path).name
    return DocMetadata(
        doc_id=doc_id,
        rel_path=rel_path,
        page_count=int(page_count),
        top_level_folder=top_level_folder,
        doj_url=str(doj_url) if doj_url else None,
        doc_type_final=str(doc_type_final) if doc_type_final else None,
        content_type=str(content_type) if content_type else None,
        title=str(title) if title else None,
    )


def _collect_doc_mentions(doc, *, max_names_per_doc: int) -> Tuple[Dict[str, Dict[str, object]], bool]:
    mentions: Dict[str, Dict[str, object]] = {}
    exceeded = False
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        try:
            text = page.get_text("text") or ""
        except Exception:
            text = ""
        if not text:
            continue
        page_num = page_index + 1
        names = extract_names_from_text(text)
        for normalized in names:
            canonical_key = normalized.canonical_key
            entry = mentions.get(canonical_key)
            if entry is None:
                if max_names_per_doc and len(mentions) >= max_names_per_doc:
                    exceeded = True
                    break
                entry = {"normalized": normalized, "pages": {}}
                mentions[canonical_key] = entry
            else:
                current = entry["normalized"]
                if _prefer_display_name(current.display_name, normalized.display_name):
                    entry["normalized"] = normalized
            entry["pages"][page_num] = entry["pages"].get(page_num, 0) + 1
        if exceeded:
            break
    return mentions, exceeded


def extract_names_from_text(text: str) -> List[NormalizedName]:
    matches: List[NormalizedName] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if is_all_caps_heading(line):
            continue
        for match in _LAST_FIRST_RE.finditer(line):
            normalized = _normalize_match(match)
            if normalized:
                matches.append(normalized)
        for match in _FIRST_LAST_RE.finditer(line):
            normalized = _normalize_match(match)
            if normalized:
                matches.append(normalized)
    return matches


def _normalize_match(match: re.Match) -> Optional[NormalizedName]:
    first = match.group("first")
    last = match.group("last")
    middle = match.group("middle")
    suffix = match.group("suffix")
    return normalize_person_name(first=first, last=last, middle=middle, suffix=suffix)


def _prefer_display_name(current: str, candidate: str) -> bool:
    if not current:
        return True
    if current.isupper() and candidate and not candidate.isupper():
        return True
    return False


__all__ = [
    "run_name_index",
    "run_name_index_and_save",
    "run_name_index_and_save_for_probe",
    "extract_names_from_text",
]
