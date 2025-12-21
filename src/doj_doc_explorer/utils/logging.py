from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from .format import iso_now


def append_log(entries: Iterable[Dict[str, Any]], log_path: Path) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            payload = {"timestamp": iso_now(), **entry}
            handle.write(json.dumps(payload) + "\n")
    return log_path


__all__ = ["append_log"]
