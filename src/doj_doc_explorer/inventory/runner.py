from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..config import InventoryConfig
from ..utils.io import ensure_dir
from .outputs import write_inventory_run
from .scan import FileRecord, scan_inventory


@dataclass
class InventoryResult:
    records: List[FileRecord]
    errors: List[Dict[str, str]]
    run_dir: Path
    csv_path: Path
    summary_path: Path
    log_path: Path
    runtime_seconds: float
    summary: Dict


class InventoryRunner:
    @staticmethod
    def _resolve_root(root: Path | str) -> Path:
        return Path(root).expanduser().resolve()

    @staticmethod
    def _resolve_out_dir(out_dir: Path | str) -> Path:
        return Path(out_dir).expanduser().resolve()

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
        if not root_path.exists():
            raise ValueError(f"Dataset root does not exist: {root_path}")
        if not root_path.is_dir():
            raise ValueError(f"Dataset root must be a directory: {root_path}")
        if max_files is not None and max_files <= 0:
            raise ValueError("--max-files must be positive when provided")
        return InventoryConfig(
            root=root_path,
            out_dir=self._resolve_out_dir(out_dir),
            hash_algorithm=hash_algorithm,
            sample_bytes=sample_bytes,
            ignore_patterns=ignore_patterns or [],
            follow_symlinks=follow_symlinks,
            max_files=max_files,
        )

    def run(self, config: InventoryConfig) -> InventoryResult:
        ensure_dir(config.out_dir)
        start = time.time()
        records, errors = scan_inventory(config)
        outputs = write_inventory_run(records=records, errors=errors, config=config)
        runtime = time.time() - start
        return InventoryResult(
            records=records,
            errors=errors,
            run_dir=outputs["run_dir"],
            csv_path=outputs["csv"],
            summary_path=outputs["summary"],
            log_path=outputs["log"],
            runtime_seconds=runtime,
            summary={},
        )


__all__ = ["InventoryRunner", "InventoryResult"]
