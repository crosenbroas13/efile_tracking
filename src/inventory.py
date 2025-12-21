from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import InventoryConfig, should_ignore

CHUNK_SIZE = 1024 * 1024


@dataclass
class FileRecord:
    file_id: str
    rel_path: str
    abs_path: str
    top_level_folder: str
    extension: str
    detected_mime: str
    size_bytes: int
    created_time: Optional[str]
    modified_time: Optional[str]
    hash_value: str
    sample_hash: Optional[str]


def compute_file_id(rel_path: str, size: int, modified_time: float) -> str:
    base = f"{rel_path}|{size}|{modified_time:.6f}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def detect_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def isoformat(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def compute_hashes(path: Path, algorithm: str, sample_bytes: int = 0) -> Tuple[str, Optional[str]]:
    algo = algorithm.lower()
    if algo == "none":
        return "", None
    try:
        hasher = hashlib.new(algo)
    except ValueError:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    sample_hasher: Optional[hashlib._Hash] = None
    if sample_bytes > 0:
        sample_hasher = hashlib.new(algo)

    total_read = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            if sample_hasher is not None and total_read < sample_bytes:
                remaining = sample_bytes - total_read
                sample_hasher.update(chunk[:remaining])
                total_read += len(chunk)
    return hasher.hexdigest(), sample_hasher.hexdigest() if sample_hasher else None


def _top_level_folder(rel_path: Path) -> str:
    parts = rel_path.parts
    return parts[0] if parts else ""


def scan_inventory(config: InventoryConfig) -> Tuple[List[FileRecord], List[Dict[str, str]]]:
    records: List[FileRecord] = []
    errors: List[Dict[str, str]] = []
    root = config.root.resolve()
    ignore_patterns = config.effective_ignore()
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=config.follow_symlinks):
        current_dir = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not should_ignore(current_dir / d, root, ignore_patterns)]

        for name in filenames:
            abs_path = current_dir / name
            try:
                if should_ignore(abs_path, root, ignore_patterns):
                    continue
                rel_path = abs_path.relative_to(root)
                stat = abs_path.stat()
                hash_value, sample_hash = ("", None)
                if config.hash_enabled():
                    hash_value, sample_hash = compute_hashes(abs_path, config.hash_algorithm, config.sample_bytes)
                record = FileRecord(
                    file_id=compute_file_id(rel_path.as_posix(), stat.st_size, stat.st_mtime),
                    rel_path=rel_path.as_posix(),
                    abs_path=str(abs_path),
                    top_level_folder=_top_level_folder(rel_path),
                    extension=abs_path.suffix.lower().lstrip("."),
                    detected_mime=detect_mime(abs_path),
                    size_bytes=stat.st_size,
                    created_time=isoformat(stat.st_ctime) if stat.st_ctime else None,
                    modified_time=isoformat(stat.st_mtime) if stat.st_mtime else None,
                    hash_value=hash_value,
                    sample_hash=sample_hash,
                )
                records.append(record)
                files_scanned += 1
                if config.max_files and files_scanned >= config.max_files:
                    return records, errors
            except (OSError, PermissionError) as exc:
                errors.append({"path": str(abs_path), "error": str(exc)})
            except ValueError as exc:
                errors.append({"path": str(abs_path), "error": str(exc)})
    return records, errors
