from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from ..config import ProbeRunConfig, new_run_id
from ..utils.git import current_git_commit
from ..utils.io import ensure_dir, read_json, update_run_index, write_json, write_pointer

PROBE_POINTER = "LATEST.json"


def _has_pyarrow() -> bool:
    try:  # pragma: no cover
        import pyarrow  # noqa: F401

        return True
    except Exception:  # pragma: no cover
        return False


def _write_table(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        df.to_csv(path.with_suffix(".csv"), index=False)
        return
    if _has_pyarrow():
        df.to_parquet(path.with_suffix(".parquet"), index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _summarize(docs_df: pd.DataFrame, pages_df: pd.DataFrame, config: ProbeRunConfig, meta: Dict) -> Dict:
    total_pdfs = int(len(docs_df))
    total_pages = int(len(pages_df))
    if total_pages == 0 and "page_count" in docs_df.columns:
        total_pages = int(pd.to_numeric(docs_df["page_count"], errors="coerce").fillna(0).sum())

    classification_counts = (
        docs_df["classification"].value_counts(dropna=False).to_dict()
        if "classification" in docs_df.columns
        else {}
    )
    classification_pct = (
        {label: (count / total_pdfs) if total_pdfs else 0 for label, count in classification_counts.items()}
        if classification_counts
        else {}
    )

    pages_with_text = 0
    if "has_text" in pages_df.columns:
        pages_with_text = int(pages_df[pages_df["has_text"] == True].shape[0])  # noqa: E712
    elif "pages_with_text" in docs_df.columns:
        pages_with_text = int(pd.to_numeric(docs_df["pages_with_text"], errors="coerce").fillna(0).sum())

    baseline_ocr_pages = max(total_pages - pages_with_text, 0)
    ignored_counts = meta.get("ignored_non_pdf_files", {}) if meta else {}
    ignored_mime_counts = meta.get("ignored_non_pdf_mime_types", {}) if meta else {}

    summary = {
        "total_pdfs": total_pdfs,
        "total_pages": total_pages,
        "classification_counts": classification_counts,
        "classification_pct": classification_pct,
        "ignored_non_pdf_files": ignored_counts,
        "ignored_non_pdf_mime_types": ignored_mime_counts,
        "ignored_non_pdf_total": int(sum(ignored_counts.values())) if ignored_counts else 0,
        "pages_with_text": pages_with_text,
        "pages_without_text": baseline_ocr_pages,
        "estimated_ocr_pages_baseline": baseline_ocr_pages,
        "estimated_ocr_pages_baseline_pct": (baseline_ocr_pages / total_pages) if total_pages else 0,
    }
    if "text_coverage_pct" in docs_df:
        top_scanned = docs_df.sort_values("text_coverage_pct").head(20)
        summary["top_scanned_docs"] = top_scanned[["doc_id", "rel_path", "text_coverage_pct"]].fillna(0).to_dict(orient="records")
    summary["thresholds"] = {
        "text_char_threshold": config.text_char_threshold,
        "doc_text_pct_text": config.doc_text_pct_text,
        "doc_text_pct_scanned": config.doc_text_pct_scanned,
    }
    return summary


def _infer_inventory_label(inventory_path: Path) -> str | None:
    summary_path = inventory_path.with_name("inventory_summary.json")
    summary = read_json(summary_path)
    source_root_name = summary.get("source_root_name")
    if source_root_name:
        return str(source_root_name)
    return None


def _infer_source_root(inventory_path: Path) -> tuple[Path, str]:
    run_log = read_json(inventory_path.with_name("run_log.json"))
    root_value = run_log.get("root")
    root_name = run_log.get("source_root_name")
    if root_value:
        source_root = Path(root_value)
    else:
        source_root = inventory_path
    if not root_name:
        summary = read_json(inventory_path.with_name("inventory_summary.json"))
        root_name = summary.get("source_root_name") or source_root.name
    return source_root, root_name


def write_probe_outputs(
    pages_df: pd.DataFrame, docs_df: pd.DataFrame, config: ProbeRunConfig, meta: Dict
) -> Path:
    probe_root = ensure_dir(Path(config.paths.outputs_root) / "probes")
    probe_run_id = new_run_id("probe", label=_infer_inventory_label(config.paths.inventory))
    run_dir = probe_root / probe_run_id
    ensure_dir(run_dir)

    pages_df = pages_df.copy()
    docs_df = docs_df.copy()
    pages_df.insert(0, "probe_run_id", probe_run_id)
    docs_df.insert(0, "probe_run_id", probe_run_id)

    _write_table(pages_df, run_dir / "readiness_pages")
    _write_table(docs_df, run_dir / "readiness_docs")

    summary = _summarize(docs_df, pages_df, config, meta)
    summary_path = write_json(run_dir / "probe_summary.json", summary)

    run_log = {
        "probe_run_id": probe_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_path": str(config.paths.inventory),
        "output_root": str(config.paths.outputs_root),
        "config": config.run_args,
        "meta": meta,
        "git_commit": current_git_commit(),
    }
    log_path = write_json(run_dir / "probe_run_log.json", run_log)

    pointer_payload = {
        "probe_run_id": probe_run_id,
        "run_dir": str(Path("probes") / probe_run_id),
        "inventory": str(config.paths.inventory),
        "summary": str(Path("probes") / probe_run_id / "probe_summary.json"),
    }
    write_pointer(probe_root, PROBE_POINTER, pointer_payload)
    source_root, source_root_name = _infer_source_root(config.paths.inventory)
    inventory_run_log = read_json(config.paths.inventory.with_name("run_log.json"))
    inventory_run_id = inventory_run_log.get("inventory_run_id") or config.paths.inventory.parent.name
    update_run_index(
        Path(config.paths.outputs_root),
        source_root=source_root,
        source_root_name=source_root_name,
        probe={
            "run_id": probe_run_id,
            "run_dir": str(Path("probes") / probe_run_id),
            "summary": str(Path("probes") / probe_run_id / "probe_summary.json"),
            "run_log": str(Path("probes") / probe_run_id / "probe_run_log.json"),
            "inventory": str(config.paths.inventory),
            "inventory_run_id": inventory_run_id,
            "timestamp": run_log["timestamp"],
        },
    )

    return run_dir


__all__ = ["write_probe_outputs"]
