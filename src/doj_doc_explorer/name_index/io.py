from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from ..utils.git import current_git_commit
from ..utils.io import ensure_dir, read_json, write_json, write_pointer
from ..utils.run_ids import new_run_id
from .config import NameIndexRunConfig


NAME_INDEX_POINTER = "LATEST.json"


def list_name_index_runs(out_dir: str) -> List[Dict]:
    root = Path(out_dir) / "name_index"
    if not root.exists():
        return []
    runs: List[Dict] = []
    for run_dir in sorted(root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        run_log = _read_json(run_dir / "name_index_run_log.json")
        summary = _read_json(run_dir / "name_index_summary.json")
        timestamp = _parse_timestamp(run_log.get("timestamp") if run_log else None)
        if timestamp is None:
            timestamp = _parse_timestamp(run_id)
        runs.append(
            {
                "name_index_run_id": run_id,
                "run_dir": run_dir,
                "run_log": run_log,
                "summary": summary,
                "timestamp": timestamp,
            }
        )
    runs.sort(key=lambda r: r.get("timestamp") or datetime.min, reverse=True)
    return runs


def load_name_index_run(out_dir: str, run_id: str) -> Tuple[List[Dict], Dict, Dict]:
    run_dir = Path(out_dir) / "name_index" / run_id
    records = _read_jsonl(run_dir / "name_index.jsonl")
    summary = _read_json(run_dir / "name_index_summary.json")
    run_log = _read_json(run_dir / "name_index_run_log.json")
    return records, summary, run_log


def load_latest_name_index(out_dir: str) -> Tuple[List[Dict], Dict, Dict]:
    pointer = _read_json(Path(out_dir) / "name_index" / NAME_INDEX_POINTER)
    run_id = pointer.get("name_index_run_id")
    if not run_id:
        return [], {}, {}
    return load_name_index_run(out_dir, run_id)


def write_name_index_outputs(
    records: List[Dict[str, object]],
    public_records: List[Dict[str, object]],
    config: NameIndexRunConfig,
    meta: Dict[str, object],
) -> Path:
    index_root = ensure_dir(Path(config.outputs_root) / "name_index")
    run_id = new_run_id("name_index", label=config.inventory_path.parent.name)
    run_dir = index_root / run_id
    ensure_dir(run_dir)

    _write_jsonl(run_dir / "name_index.jsonl", records)
    write_json(run_dir / "public_name_index.json", public_records)

    summary = _summarize(records, meta)
    summary["inventory_run_id"] = _resolve_inventory_run_id(config)
    summary["probe_run_id"] = config.probe_run_dir.name
    summary["text_scan_run_id"] = config.text_scan_run_dir.name
    summary["name_index_run_id"] = run_id
    summary["timestamp"] = datetime.now(timezone.utc).isoformat()
    summary["config"] = config.run_args
    write_json(run_dir / "name_index_summary.json", summary)

    run_log = {
        "name_index_run_id": run_id,
        "timestamp": summary["timestamp"],
        "inventory_path": str(config.inventory_path),
        "inventory_run_id": summary["inventory_run_id"],
        "probe_run_id": summary["probe_run_id"],
        "probe_run_dir": str(config.probe_run_dir),
        "text_scan_run_id": summary["text_scan_run_id"],
        "text_scan_run_dir": str(config.text_scan_run_dir),
        "outputs_root": str(config.outputs_root),
        "config": config.run_args,
        "git_commit": current_git_commit(),
        "meta": meta,
    }
    write_json(run_dir / "name_index_run_log.json", run_log)

    pointer_payload = {
        "name_index_run_id": run_id,
        "run_dir": str(Path("name_index") / run_id),
        "inventory": str(config.inventory_path),
        "probe_run_dir": str(config.probe_run_dir),
        "text_scan_run_dir": str(config.text_scan_run_dir),
        "summary": str(Path("name_index") / run_id / "name_index_summary.json"),
        "public": str(Path("name_index") / run_id / "public_name_index.json"),
    }
    write_pointer(index_root, NAME_INDEX_POINTER, pointer_payload)
    return run_dir


def _summarize(records: List[Dict[str, object]], meta: Dict[str, object]) -> Dict[str, object]:
    name_count = len(records)
    doc_ids: set[str] = set()
    total_mentions = 0
    for record in records:
        docs = record.get("docs", [])
        for doc in docs:
            doc_id = doc.get("doc_id")
            if doc_id:
                doc_ids.add(str(doc_id))
        total_mentions += int(record.get("total_count") or 0)
    summary = {
        "total_names": name_count,
        "total_docs_with_mentions": len(doc_ids),
        "total_mentions": total_mentions,
    }
    summary.update(meta or {})
    return summary


def _resolve_inventory_run_id(config: NameIndexRunConfig) -> str:
    run_log_path = config.inventory_path.with_name("run_log.json")
    run_id = config.inventory_path.parent.name
    if run_log_path.exists():
        data = read_json(run_log_path)
        run_id = data.get("inventory_run_id") or run_id
    return run_id


def _read_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records: List[Dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _write_jsonl(path: Path, records: List[Dict[str, object]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


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


__all__ = [
    "NAME_INDEX_POINTER",
    "list_name_index_runs",
    "load_name_index_run",
    "load_latest_name_index",
    "write_name_index_outputs",
]
