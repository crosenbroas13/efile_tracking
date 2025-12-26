from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def append_index_row(index_path: Path, row: Dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not index_path.exists()
    with index_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def build_meta_payload(
    base: Dict[str, Any],
    warnings: Iterable[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    payload = dict(base)
    payload["warnings"] = list(warnings)
    payload["run_timestamp"] = utc_now_iso()
    payload["config"] = config
    return payload

