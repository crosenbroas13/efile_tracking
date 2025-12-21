from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


def _read_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _load_table(run_dir: Path, stem: str) -> pd.DataFrame:
    parquet_path = run_dir / f"{stem}.parquet"
    csv_path = run_dir / f"{stem}.csv"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


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


def list_probe_runs(out_dir: str) -> List[Dict]:
    root = Path(out_dir)
    probe_root = root / "probes"
    if not probe_root.exists():
        return []

    runs: List[Dict] = []
    for run_dir in sorted(probe_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        run_log = _read_json(run_dir / "probe_run_log.json")
        summary = _read_json(run_dir / "probe_summary.json")
        timestamp = _parse_timestamp(run_log.get("timestamp") if run_log else None)
        if timestamp is None:
            timestamp = _parse_timestamp(run_id)

        runs.append(
            {
                "probe_run_id": run_id,
                "run_dir": run_dir,
                "run_log": run_log,
                "summary": summary,
                "timestamp": timestamp,
            }
        )

    runs.sort(key=lambda r: r.get("timestamp") or datetime.min, reverse=True)
    return runs


def load_probe_run(out_dir: str, probe_run_id: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict, Dict]:
    run_dir = Path(out_dir) / "probes" / probe_run_id
    pages_df = _load_table(run_dir, "readiness_pages")
    docs_df = _load_table(run_dir, "readiness_docs")
    summary = _read_json(run_dir / "probe_summary.json")
    run_log = _read_json(run_dir / "probe_run_log.json")
    return docs_df, pages_df, summary, run_log


__all__ = ["list_probe_runs", "load_probe_run"]
