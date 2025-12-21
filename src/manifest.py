import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .inventory import FileRecord


def write_inventory_csv(records: List[FileRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "inventory.csv"
    headers = [
        "file_id",
        "rel_path",
        "abs_path",
        "top_level_folder",
        "extension",
        "detected_mime",
        "size_bytes",
        "created_time",
        "modified_time",
        "hash_value",
        "sample_hash",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
    return csv_path


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


def write_summary_json(summary: Dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inventory_summary.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return json_path


def append_run_log(entry: Dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return log_path
