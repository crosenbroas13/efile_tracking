"""Application-friendly inventory runner for IDE use.

This module exposes a thin wrapper around the core inventory functions
so that developers can trigger scans from an IDE like PyCharm without
needing to memorize CLI flags. The runner handles path validation,
builds the configuration, and returns a structured result object.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config import InventoryConfig, normalize_patterns
from .inventory import FileRecord, scan_inventory
from .manifest import append_run_log, build_summary, write_inventory_csv, write_summary_json


@dataclass
class InventoryResult:
    """Structured results from an inventory run."""

    records: List[FileRecord]
    errors: List[Dict[str, str]]
    csv_path: Path
    summary_path: Path
    log_path: Path
    runtime_seconds: float
    summary: Dict


class InventoryRunner:
    """High-level runner that coordinates inventory tasks."""

    @staticmethod
    def _git_commit() -> str:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            return commit
        except Exception:
            return "unknown"

    @staticmethod
    def _validate_root(root: Path) -> None:
        if not root.exists():
            raise ValueError(
                f"Dataset root does not exist: {root}. Provide a folder that already contains your files to scan."
            )
        if not root.is_dir():
            raise ValueError(f"Dataset root must be a directory, but received: {root}")

    @staticmethod
    def _resolve_root(root: Path | str) -> Path:
        """Resolve the provided root, correcting common absolute-path typos.

        Developers sometimes paste an absolute path without the leading slash
        (for example, `Users/...` on macOS). In that case, the path resolves
        relative to the repo and validation fails with a confusing message.
        When we detect that pattern and the intended folder exists, we
        normalize it to the real absolute location.
        """

        raw_root = Path(root).expanduser()

        if raw_root.is_absolute():
            return raw_root.resolve()

        probable_absolute = Path("/", *raw_root.parts)
        if probable_absolute.exists():
            return probable_absolute.resolve()

        return raw_root.resolve()

    @staticmethod
    def _resolve_out_dir(out_dir: Path | str) -> Path:
        """Normalize the output directory, fixing common absolute-path typos.

        Users sometimes paste an absolute path without its leading slash. When
        the parent folder exists (for example, `/Users/alex/Downloads`), treat
        it as an absolute path so we do not quietly write outputs in the wrong
        project directory. For everything else, return an absolute path to keep
        logs and printouts consistent.
        """

        raw_out = Path(out_dir).expanduser()

        if raw_out.is_absolute():
            return raw_out.resolve()

        probable_absolute = Path("/", *raw_out.parts)
        if probable_absolute.exists() or probable_absolute.parent.exists():
            return probable_absolute.resolve()

        return raw_out.resolve()

    def create_config(
        self,
        *,
        root: Path | str,
        out_dir: Path | str,
        hash_algorithm: str = "sha256",
        sample_bytes: int = 0,
        ignore_patterns: Optional[List[str]] = None,
        follow_symlinks: bool = False,
        max_files: Optional[int] = None,
    ) -> InventoryConfig:
        root_path = self._resolve_root(root)
        self._validate_root(root_path)
        if max_files is not None and max_files <= 0:
            raise ValueError("--max-files must be a positive integer when provided.")

        return InventoryConfig(
            root=root_path,
            out_dir=self._resolve_out_dir(out_dir),
            hash_algorithm=hash_algorithm,
            sample_bytes=sample_bytes,
            ignore_patterns=normalize_patterns(ignore_patterns or []),
            follow_symlinks=follow_symlinks,
            max_files=max_files,
        )

    def run(self, config: InventoryConfig) -> InventoryResult:
        start = time.time()
        records, errors = scan_inventory(config)
        csv_path = write_inventory_csv(records, config.out_dir)
        summary = build_summary(records)
        summary_path = write_summary_json(summary, config.out_dir)
        runtime = time.time() - start

        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(config.root),
            "args": {
                "hash": config.hash_algorithm,
                "sample_bytes": config.sample_bytes,
                "ignore": config.ignore_patterns,
                "follow_symlinks": config.follow_symlinks,
                "max_files": config.max_files,
            },
            "runtime_seconds": runtime,
            "files_scanned": len(records),
            "errors_count": len(errors),
            "git_commit": self._git_commit(),
            "errors": errors,
        }
        log_path = append_run_log(log_entry, config.out_dir)

        return InventoryResult(
            records=records,
            errors=errors,
            csv_path=csv_path,
            summary_path=summary_path,
            log_path=log_path,
            runtime_seconds=runtime,
            summary=summary,
        )
