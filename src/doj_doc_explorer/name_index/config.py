from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class NameIndexRunConfig:
    inventory_path: Path
    probe_run_dir: Path
    text_scan_run_dir: Path
    outputs_root: Path
    only_verified_good: bool = True
    min_total_count: int = 1
    max_names_per_doc: int = 500

    @property
    def run_args(self) -> Dict[str, object]:
        return {
            "inventory_path": str(self.inventory_path),
            "probe_run_dir": str(self.probe_run_dir),
            "text_scan_run_dir": str(self.text_scan_run_dir),
            "outputs_root": str(self.outputs_root),
            "only_verified_good": self.only_verified_good,
            "min_total_count": self.min_total_count,
            "max_names_per_doc": self.max_names_per_doc,
        }


__all__ = ["NameIndexRunConfig"]
