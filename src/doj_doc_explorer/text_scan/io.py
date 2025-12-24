from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..utils.io import load_table
from ..utils.paths import normalize_rel_path


def _read_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y%m%d_%H%M%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def list_text_scan_runs(out_dir: str) -> List[Dict]:
    root = Path(out_dir) / "text_scan"
    if not root.exists():
        return []
    runs: List[Dict] = []
    for run_dir in sorted(root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        run_log = _read_json(run_dir / "text_scan_run_log.json")
        summary = _read_json(run_dir / "text_scan_summary.json")
        timestamp = _parse_timestamp(run_log.get("timestamp") if run_log else None)
        if timestamp is None:
            timestamp = _parse_timestamp(run_id)
        runs.append(
            {
                "text_scan_run_id": run_id,
                "run_dir": run_dir,
                "run_log": run_log,
                "summary": summary,
                "timestamp": timestamp,
            }
        )
    runs.sort(key=lambda r: r.get("timestamp") or datetime.min, reverse=True)
    return runs


def load_text_scan_run(out_dir: str, run_id: str) -> Tuple[pd.DataFrame, Dict, Dict]:
    run_dir = Path(out_dir) / "text_scan" / run_id
    df = load_table(run_dir / "doc_text_signals")
    summary = _read_json(run_dir / "text_scan_summary.json")
    run_log = _read_json(run_dir / "text_scan_run_log.json")
    return df, summary, run_log


def load_latest_text_scan(out_dir: str) -> Tuple[pd.DataFrame, Dict, Dict]:
    pointer = _read_json(Path(out_dir) / "text_scan" / "LATEST.json")
    run_id = pointer.get("text_scan_run_id")
    if not run_id:
        return pd.DataFrame(), {}, {}
    return load_text_scan_run(out_dir, run_id)


def merge_text_scan_signals(docs_df: pd.DataFrame, signals_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    docs_df = docs_df.copy()
    signals_df = signals_df.copy()
    if docs_df.empty or signals_df.empty:
        return docs_df, {"merged": False, "reason": "missing_data"}
    if "rel_path" not in docs_df.columns or "rel_path" not in signals_df.columns:
        return docs_df, {"merged": False, "reason": "missing_rel_path"}

    docs_df["rel_path_norm"] = docs_df["rel_path"].astype(str).map(normalize_rel_path)
    signals_df["rel_path_norm"] = signals_df["rel_path"].astype(str).map(normalize_rel_path)
    signals_df = signals_df.drop_duplicates(subset=["rel_path_norm"])

    docs_paths = set(docs_df["rel_path_norm"])
    signal_paths = set(signals_df["rel_path_norm"])
    coverage = len(docs_paths & signal_paths) / len(docs_paths) if docs_paths else 0.0
    if coverage == 0.0:
        return docs_df.drop(columns=["rel_path_norm"]), {
            "merged": False,
            "reason": "rel_path_mismatch",
            "coverage": coverage,
        }

    merge_cols = [
        "text_quality_label",
        "text_quality_score",
        "content_type_pred",
        "content_type_confidence",
    ]
    available_cols = [col for col in merge_cols if col in signals_df.columns]
    merged = docs_df.merge(signals_df[available_cols + ["rel_path_norm"]], on="rel_path_norm", how="left")
    merged = merged.drop(columns=["rel_path_norm"])
    return merged, {"merged": True, "coverage": coverage}


__all__ = [
    "list_text_scan_runs",
    "load_text_scan_run",
    "load_latest_text_scan",
    "merge_text_scan_signals",
]
