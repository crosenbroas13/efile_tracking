from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from ..config import InventoryConfig, new_run_id
from ..utils.git import current_git_commit
from ..utils.io import ensure_dir, write_json, write_pointer
from .summarize import build_summary
from .scan import FileRecord


INVENTORY_POINTER = "LATEST.json"


def write_inventory_csv(records: List[FileRecord], run_dir: Path) -> Path:
    ensure_dir(run_dir)
    csv_path = run_dir / "inventory.csv"
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


def write_inventory_run(
    *,
    records: List[FileRecord],
    errors: List[Dict[str, str]],
    config: InventoryConfig,
    run_id: Optional[str] = None,
) -> Dict[str, Path]:
    inventory_root = ensure_dir(Path(config.out_dir) / "inventory")
    root_name = config.root.resolve().name
    run_id = run_id or new_run_id("inventory", label=root_name)
    run_dir = inventory_root / run_id
    ensure_dir(run_dir)

    csv_path = write_inventory_csv(records, run_dir)
    summary = build_summary(records)
    summary["source_root_name"] = root_name
    summary_path = write_json(run_dir / "inventory_summary.json", summary)

    log_entry = {
        "inventory_run_id": run_id,
        "root": str(config.root),
        "source_root_name": root_name,
        "args": {
            "hash": config.hash_algorithm,
            "sample_bytes": config.sample_bytes,
            "ignore": config.ignore_patterns,
            "follow_symlinks": config.follow_symlinks,
            "max_files": config.max_files,
        },
        "files_scanned": len(records),
        "errors_count": len(errors),
        "errors": errors,
        "git_commit": current_git_commit(),
    }
    log_path = write_json(run_dir / "run_log.json", log_entry)
    legacy_log = inventory_root / "run_log.jsonl"
    with legacy_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(log_entry) + "\n")

    pointer_payload = {
        "inventory_run_id": run_id,
        "inventory_csv": str(Path("inventory") / run_id / "inventory.csv"),
        "summary": str(Path("inventory") / run_id / "inventory_summary.json"),
        "run_log": str(Path("inventory") / run_id / "run_log.json"),
        "source_root_name": root_name,
    }
    write_pointer(inventory_root, INVENTORY_POINTER, pointer_payload)

    # Backward compatibility: keep flat files up to date
    csv_copy = Path(config.out_dir) / "inventory.csv"
    summary_copy = Path(config.out_dir) / "inventory_summary.json"
    csv_copy.write_bytes(csv_path.read_bytes())
    summary_copy.write_bytes(summary_path.read_bytes())

    return {
        "csv": csv_path,
        "summary": summary_path,
        "log": log_path,
        "run_dir": run_dir,
        "pointer": inventory_root / INVENTORY_POINTER,
    }
__all__ = ["write_inventory_run", "write_inventory_csv"]
