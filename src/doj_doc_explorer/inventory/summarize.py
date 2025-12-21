from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List

from .scan import FileRecord


def build_summary(records: List[FileRecord], top_n: int = 10) -> Dict:
    total_bytes = sum(r.size_bytes for r in records)
    ext_counts = Counter(r.extension or "" for r in records)
    mime_counts = Counter(r.detected_mime or "" for r in records)

    largest = sorted(records, key=lambda r: r.size_bytes, reverse=True)[:top_n]
    largest_payload = [
        {
            "rel_path": r.rel_path,
            "size_bytes": r.size_bytes,
            "detected_mime": r.detected_mime,
        }
        for r in largest
    ]

    folder_rollup: Dict[str, Dict[str, int]] = {}
    for r in records:
        folder = r.top_level_folder or ""
        if folder not in folder_rollup:
            folder_rollup[folder] = {"files": 0, "total_bytes": 0}
        folder_rollup[folder]["files"] += 1
        folder_rollup[folder]["total_bytes"] += r.size_bytes

    return {
        "totals": {"files": len(records), "total_bytes": total_bytes},
        "counts_by_extension": dict(ext_counts),
        "counts_by_mime": dict(mime_counts),
        "top_largest": largest_payload,
        "folders": folder_rollup,
    }


__all__ = ["build_summary"]
