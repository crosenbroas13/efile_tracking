from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

from src.git_utils import current_git_commit
from src.probe_config import ProbeConfig


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _has_pyarrow() -> bool:
    try:  # pragma: no cover - import guard
        import pyarrow  # noqa: F401

        return True
    except Exception:
        return False


def _write_table(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        df.to_csv(path.with_suffix(".csv"), index=False)
        return
    if _has_pyarrow():
        df.to_parquet(path.with_suffix(".parquet"), index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _summarize(
    docs_df: pd.DataFrame, pages_df: pd.DataFrame, config: ProbeConfig, meta: Dict
) -> Dict:
    summary = {
        "total_pdfs": int(len(docs_df)),
        "total_pages": int(len(pages_df)),
        "classification_counts": docs_df["classification"].value_counts(dropna=False).to_dict()
        if "classification" in docs_df.columns
        else {},
    }
    ignored_counts = meta.get("ignored_non_pdf_files", {}) if meta else {}
    summary["ignored_non_pdf_files"] = ignored_counts
    summary["ignored_non_pdf_total"] = int(sum(ignored_counts.values())) if ignored_counts else 0
    if "is_mostly_black" in pages_df.columns:
        mostly_black_count = int(pages_df[pages_df["is_mostly_black"] == True].shape[0])  # noqa: E712
        summary["mostly_black_pages"] = mostly_black_count
        summary["mostly_black_pct"] = (mostly_black_count / summary["total_pages"]) if summary["total_pages"] else 0
        summary["estimated_ocr_avoidable_pages"] = mostly_black_count
        summary["estimated_ocr_avoidable_pct"] = summary["mostly_black_pct"]
    if "mostly_black_pct" in docs_df:
        top_black = docs_df.sort_values("mostly_black_pct", ascending=False).head(20)
        summary["top_black_docs"] = top_black[["doc_id", "rel_path", "mostly_black_pct"]].fillna(0).to_dict(orient="records")
    if "text_coverage_pct" in docs_df:
        top_scanned = docs_df.sort_values("text_coverage_pct").head(20)
        summary["top_scanned_docs"] = top_scanned[["doc_id", "rel_path", "text_coverage_pct"]].fillna(0).to_dict(orient="records")
    summary["thresholds"] = {
        "text_char_threshold": config.text_char_threshold,
        "doc_text_pct_text": config.doc_text_pct_text,
        "doc_text_pct_scanned": config.doc_text_pct_scanned,
        "black_threshold_intensity": config.black_threshold_intensity,
        "mostly_black_ratio": config.mostly_black_ratio,
        "render_dpi": config.render_dpi,
        "center_crop_pct": config.center_crop_pct,
        "use_center_crop": config.use_center_crop,
    }
    return summary


def write_probe_outputs(
    pages_df: pd.DataFrame, docs_df: pd.DataFrame, config: ProbeConfig, meta: Dict
) -> Path:
    probe_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(config.output_root) / "probes" / probe_run_id
    _ensure_dir(run_dir)

    pages_df = pages_df.copy()
    docs_df = docs_df.copy()
    pages_df.insert(0, "probe_run_id", probe_run_id)
    docs_df.insert(0, "probe_run_id", probe_run_id)

    _write_table(pages_df, run_dir / "readiness_pages")
    _write_table(docs_df, run_dir / "readiness_docs")

    summary = _summarize(docs_df, pages_df, config, meta)
    summary_path = run_dir / "probe_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    run_log = {
        "probe_run_id": probe_run_id,
        "inventory_path": str(config.inventory_path),
        "output_root": str(config.output_root),
        "config": config.to_dict(),
        "meta": meta,
        "git_commit": current_git_commit(),
    }
    log_path = run_dir / "probe_run_log.json"
    log_path.write_text(json.dumps(run_log, indent=2))

    return run_dir


__all__ = ["write_probe_outputs"]
