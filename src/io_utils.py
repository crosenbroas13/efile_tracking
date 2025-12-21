"""Helpers for loading inventory artifacts with caching and validation."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

try:  # pragma: no cover - exercised in Streamlit runtime
    import streamlit as st

    cache_data = st.cache_data
except Exception:  # pragma: no cover - fallback for non-Streamlit contexts
    def cache_data(**cache_kwargs):
        def decorator(func):
            cached = lru_cache(maxsize=None)(func)
            return cached

        return decorator


DEFAULT_OUT_DIR = Path("./outputs")


def _ensure_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


@cache_data(show_spinner=False)
def list_inventory_candidates(out_dir: Path | str) -> List[Path]:
    """Return inventory CSV paths under the provided output directory."""

    out_path = _ensure_path(out_dir)
    if not out_path.exists():
        return []

    return sorted(out_path.glob("**/inventory.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


@cache_data(show_spinner=False)
def load_inventory_df(csv_path: Path | str) -> pd.DataFrame:
    """Load the inventory CSV with safe dtypes for large files."""

    path = _ensure_path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Inventory not found at {path}")

    dtype_overrides: Dict[str, str] = {
        "rel_path": "string",
        "abs_path": "string",
        "top_level_folder": "string",
        "extension": "string",
        "detected_mime": "string",
        "hash_value": "string",
        "sample_hash": "string",
    }

    df = pd.read_csv(
        path,
        dtype=dtype_overrides,
        keep_default_na=False,
        dtype_backend="pyarrow",
        low_memory=False,
    )

    if "size_bytes" in df.columns:
        df["size_bytes"] = pd.to_numeric(df["size_bytes"], errors="coerce")

    return df


@cache_data(show_spinner=False)
def load_inventory_summary(summary_path: Path | str) -> Optional[Dict]:
    """Load the inventory summary JSON when present."""

    path = _ensure_path(summary_path)
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@cache_data(show_spinner=False)
def load_run_log(out_dir: Path | str) -> List[Dict]:
    """Read the run log JSONL into a list of dicts (latest first)."""

    out_path = _ensure_path(out_dir)
    log_path = out_path / "run_log.jsonl"
    if not log_path.exists():
        return []

    entries: List[Dict] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries


def pick_default_inventory(out_dir: Path | str) -> Optional[Path]:
    """Choose the most recent inventory CSV if available."""

    candidates = list_inventory_candidates(out_dir)
    if not candidates:
        return None
    return candidates[0]


def format_run_label(path: Path) -> str:
    """Generate a friendly label for a discovered inventory path."""

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None

    base = path.parent.name or path.parent.as_posix()
    label = f"{base}/inventory.csv"
    if mtime:
        label = f"{label} (modified {pd.to_datetime(mtime, unit='s').strftime('%Y-%m-%d %H:%M:%S')})"
    return label


def normalize_out_dir(out_dir: Path | str) -> Path:
    return _ensure_path(out_dir)
