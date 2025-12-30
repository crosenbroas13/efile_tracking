from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.io_utils import load_inventory_df

from ..text_scan.io import load_latest_text_scan, merge_text_scan_signals
from ..utils.io import latest_probe, load_table, read_json, write_json
from ..utils.paths import normalize_rel_path


def _coerce_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return default
    except Exception:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_str(value: object) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text if text else None


def _load_probe_docs(outputs_root: Path, probe_run_id: str) -> pd.DataFrame:
    run_dir = outputs_root / "probes" / probe_run_id
    if not run_dir.exists():
        return pd.DataFrame()
    return load_table(run_dir / "readiness_docs")


def _resolve_latest_probe_id(outputs_root: Path) -> Optional[str]:
    latest = latest_probe(outputs_root)
    if not latest:
        return None
    run_dir, pointer = latest
    return pointer.get("probe_run_id") or run_dir.name


def _merge_text_scan_if_available(
    probe_docs: pd.DataFrame, outputs_root: Path, probe_run_id: Optional[str]
) -> tuple[pd.DataFrame, Optional[str]]:
    if probe_docs.empty:
        return probe_docs, None
    text_scan_df, summary, _run_log = load_latest_text_scan(str(outputs_root))
    if text_scan_df.empty or not summary:
        return probe_docs, None
    summary_probe_id = summary.get("probe_run_id")
    if probe_run_id and summary_probe_id and summary_probe_id != probe_run_id:
        return probe_docs, None
    merged, _meta = merge_text_scan_signals(probe_docs, text_scan_df)
    return merged, summary.get("text_scan_run_id")


def _build_probe_lookup(probe_docs: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if probe_docs.empty or "rel_path" not in probe_docs.columns:
        return {}
    probe_docs = probe_docs.copy()
    probe_docs["rel_path_norm"] = probe_docs["rel_path"].astype(str).map(normalize_rel_path)
    probe_docs = probe_docs.drop_duplicates(subset=["rel_path_norm"])
    return probe_docs.set_index("rel_path_norm").to_dict(orient="index")


def _resolve_doc_type(extension: str, probe_row: Dict[str, Any]) -> str:
    doc_type = _coerce_str(probe_row.get("doc_type_final")) or _coerce_str(probe_row.get("doc_type"))
    if doc_type:
        return doc_type
    if extension == "pdf":
        return "PDF (unprobed)"
    if extension:
        return f"NON_PDF ({extension})"
    return "NON_PDF"


def _resolve_content_type(extension: str, probe_row: Dict[str, Any], inventory_row: pd.Series) -> Optional[str]:
    content_type = (
        _coerce_str(probe_row.get("content_type_pred"))
        or _coerce_str(probe_row.get("content_type"))
        or _coerce_str(probe_row.get("content_type_label"))
    )
    if content_type:
        return content_type
    if extension != "pdf":
        return _coerce_str(inventory_row.get("detected_mime"))
    return None


def _build_inventory_meta(inventory_path: Path, inventory_summary: Dict[str, Any]) -> Dict[str, Any]:
    source_root_name = inventory_summary.get("source_root_name") if inventory_summary else None
    inventory_totals = inventory_summary.get("totals", {}) if inventory_summary else {}
    folder_count = len(inventory_summary.get("folders", {})) if inventory_summary else None
    return {
        "run_id": inventory_path.parent.name,
        "source_root_name": source_root_name,
        "totals": inventory_totals,
        "folder_count": folder_count,
    }


def build_public_summary_payload(*, inventory_path: Path) -> Dict[str, Any]:
    inventory_summary = read_json(inventory_path.with_name("inventory_summary.json"))
    inventory_meta = _build_inventory_meta(inventory_path, inventory_summary)
    return {"meta": {"inventory": inventory_meta}}


def build_public_index_payload(
    *,
    inventory_path: Path,
    outputs_root: Path,
    probe_run_id: str | None = None,
) -> Dict[str, Any]:
    inventory_df = load_inventory_df(inventory_path)
    inventory_summary = read_json(inventory_path.with_name("inventory_summary.json"))
    inventory_meta = _build_inventory_meta(inventory_path, inventory_summary)
    source_root_name = inventory_meta.get("source_root_name")

    resolved_probe_id = probe_run_id or _resolve_latest_probe_id(outputs_root)
    probe_docs = _load_probe_docs(outputs_root, resolved_probe_id) if resolved_probe_id else pd.DataFrame()
    probe_docs, text_scan_run_id = _merge_text_scan_if_available(probe_docs, outputs_root, resolved_probe_id)
    probe_lookup = _build_probe_lookup(probe_docs)
    probe_summary = (
        read_json(outputs_root / "probes" / resolved_probe_id / "probe_summary.json") if resolved_probe_id else {}
    )
    probe_totals = {}
    probe_text = {}
    if probe_summary:
        probe_totals = {
            "pdfs": probe_summary.get("total_pdfs"),
            "pages": probe_summary.get("total_pages"),
        }
        probe_text = {
            "pages_with_text": probe_summary.get("pages_with_text"),
            "pages_without_text": probe_summary.get("pages_without_text"),
        }

    items: List[Dict[str, Any]] = []
    for _, row in inventory_df.iterrows():
        rel_path = _coerce_str(row.get("rel_path")) or ""
        rel_path_norm = normalize_rel_path(rel_path) if rel_path else ""
        extension = (_coerce_str(row.get("extension")) or "").lower()
        probe_row = probe_lookup.get(rel_path_norm, {})

        dataset = _coerce_str(row.get("dataset")) or _coerce_str(row.get("top_level_folder")) or source_root_name or "Unknown"
        title = (
            _coerce_str(row.get("title"))
            or _coerce_str(probe_row.get("title"))
            or Path(rel_path).name
            or "Untitled document"
        )
        item = {
            "id": _coerce_str(row.get("file_id")) or rel_path_norm or title,
            "title": title,
            "summary": _coerce_str(row.get("summary")) or _coerce_str(probe_row.get("summary")),
            "doc_type_final": _resolve_doc_type(extension, probe_row),
            "content_type": _resolve_content_type(extension, probe_row, row),
            "classification": _coerce_str(probe_row.get("classification")),
            "text_quality_label": _coerce_str(probe_row.get("text_quality_label")),
            "page_count": _coerce_int(probe_row.get("page_count"), default=0),
            "dataset": dataset,
            "doj_url": _coerce_str(probe_row.get("doj_url"))
            or _coerce_str(probe_row.get("source_url"))
            or _coerce_str(probe_row.get("download_url"))
            or _coerce_str(row.get("doj_url")),
            "rel_path": rel_path or None,
            "extension": extension or None,
            "detected_mime": _coerce_str(row.get("detected_mime")),
            "size_bytes": _coerce_int(row.get("size_bytes"), default=0),
            "modified_time": _coerce_str(row.get("modified_time")),
            "created_time": _coerce_str(row.get("created_time")),
        }
        items.append(item)

    items.sort(
        key=lambda item: (
            str(item.get("dataset") or ""),
            str(item.get("rel_path") or ""),
        )
    )

    meta = {
        "item_count": len(items),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "inventory_path": str(inventory_path),
        "inventory_run_id": inventory_meta.get("run_id"),
        "probe_run_id": resolved_probe_id,
        "text_scan_run_id": text_scan_run_id,
        "source_root_name": source_root_name,
        "inventory": inventory_meta,
        "probe": {
            "run_id": resolved_probe_id,
            "totals": probe_totals,
            "text": probe_text,
        },
    }
    return {"meta": meta, "items": items}


def write_public_index(payload: Dict[str, Any], output_path: Path) -> Path:
    return write_json(output_path, payload)


def write_public_summary(payload: Dict[str, Any], output_path: Path) -> Path:
    return write_json(output_path, payload)


__all__ = [
    "build_public_index_payload",
    "build_public_summary_payload",
    "write_public_index",
    "write_public_summary",
]
