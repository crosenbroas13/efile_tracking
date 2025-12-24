from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from ..utils.run_ids import new_run_id
from ..utils.git import current_git_commit
from ..utils.io import ensure_dir, read_json, write_json, write_pointer
from .config import TextScanRunConfig

TEXT_SCAN_POINTER = "LATEST.json"


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


def _summarize(df: pd.DataFrame) -> Dict[str, object]:
    total_docs = int(len(df))
    quality_counts = df["text_quality_label"].value_counts(dropna=False).to_dict() if "text_quality_label" in df else {}
    content_counts = df["content_type_pred"].value_counts(dropna=False).to_dict() if "content_type_pred" in df else {}
    avg_score = float(df["text_quality_score"].mean()) if "text_quality_score" in df and not df.empty else 0.0
    return {
        "total_docs": total_docs,
        "text_quality_counts": quality_counts,
        "content_type_counts": content_counts,
        "avg_text_quality_score": avg_score,
    }


def write_text_scan_outputs(
    df: pd.DataFrame,
    config: TextScanRunConfig,
    *,
    inventory_run_id: str,
    probe_run_id: str,
) -> Path:
    scan_root = ensure_dir(Path(config.outputs_root) / "text_scan")
    run_id = new_run_id("text_scan", label=config.inventory_path.parent.name)
    run_dir = scan_root / run_id
    ensure_dir(run_dir)

    df = df.copy()
    df.insert(0, "text_scan_run_id", run_id)
    df.insert(1, "inventory_run_id", inventory_run_id)
    df.insert(2, "probe_run_id", probe_run_id)

    _write_table(df, run_dir / "doc_text_signals")
    summary = _summarize(df)
    summary["inventory_run_id"] = inventory_run_id
    summary["probe_run_id"] = probe_run_id
    summary["text_scan_run_id"] = run_id
    summary["timestamp"] = datetime.now(timezone.utc).isoformat()
    summary["config"] = config.run_args
    summary_path = write_json(run_dir / "text_scan_summary.json", summary)

    inventory_run_log = read_json(config.inventory_path.with_name("run_log.json"))
    inventory_run_id = inventory_run_log.get("inventory_run_id") or config.inventory_path.parent.name
    run_log = {
        "text_scan_run_id": run_id,
        "timestamp": summary["timestamp"],
        "inventory_path": str(config.inventory_path),
        "inventory_run_id": inventory_run_id,
        "probe_run_id": probe_run_id,
        "probe_run_dir": str(config.probe_run_dir),
        "outputs_root": str(config.outputs_root),
        "config": config.run_args,
        "git_commit": current_git_commit(),
    }
    write_json(run_dir / "text_scan_run_log.json", run_log)

    pointer_payload = {
        "text_scan_run_id": run_id,
        "run_dir": str(Path("text_scan") / run_id),
        "inventory": str(config.inventory_path),
        "probe_run_dir": str(config.probe_run_dir),
        "summary": str(Path("text_scan") / run_id / "text_scan_summary.json"),
    }
    write_pointer(scan_root, TEXT_SCAN_POINTER, pointer_payload)
    return run_dir


__all__ = ["write_text_scan_outputs", "TEXT_SCAN_POINTER"]
