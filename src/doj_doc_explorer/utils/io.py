from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..config import DEFAULT_OUTPUT_ROOT


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Dict[str, Any]) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2))
    return path


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def write_pointer(root: Path, name: str, payload: Dict[str, Any]) -> Path:
    pointer = root / name
    return write_json(pointer, payload)


def load_pointer(root: Path, name: str) -> Dict[str, Any]:
    return read_json(root / name)


def latest_inventory(outputs_root: Path = DEFAULT_OUTPUT_ROOT) -> Optional[Path]:
    pointer = load_pointer(outputs_root / "inventory", "LATEST.json")
    if pointer.get("inventory_csv"):
        candidate = outputs_root / pointer["inventory_csv"]
        if candidate.exists():
            return candidate
    legacy = outputs_root / "inventory.csv"
    if legacy.exists():
        return legacy
    return None


def latest_probe(outputs_root: Path = DEFAULT_OUTPUT_ROOT) -> Optional[Tuple[Path, Dict[str, Any]]]:
    pointer = load_pointer(outputs_root / "probes", "LATEST.json")
    if pointer.get("run_dir"):
        run_dir = outputs_root / pointer["run_dir"]
        if run_dir.exists():
            return run_dir, pointer
    return None


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet" and path.exists():
        return pd.read_parquet(path)
    if path.exists():
        return pd.read_csv(path)
    parquet = path.with_suffix(".parquet")
    csv_path = path.with_suffix(".csv")
    if parquet.exists():
        return pd.read_parquet(parquet)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def self_check(base: Path = DEFAULT_OUTPUT_ROOT) -> Dict[str, Any]:
    outputs = ensure_dir(base)
    inventory_dir = ensure_dir(outputs / "inventory")
    probe_dir = ensure_dir(outputs / "probes")
    return {
        "outputs": str(outputs.resolve()),
        "inventory_dir": str(inventory_dir.resolve()),
        "probe_dir": str(probe_dir.resolve()),
        "inventory_pointer": str((inventory_dir / "LATEST.json").resolve()),
        "probe_pointer": str((probe_dir / "LATEST.json").resolve()),
    }


__all__ = [
    "ensure_dir",
    "write_json",
    "read_json",
    "write_pointer",
    "load_pointer",
    "latest_inventory",
    "latest_probe",
    "load_table",
    "self_check",
]
