from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional

DEFAULT_OUTPUT_ROOT = Path("outputs")
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_IGNORE = ["*.DS_Store", "Thumbs.db", "~$*"]


@dataclass
class InventoryConfig:
    root: Path
    out_dir: Path = DEFAULT_OUTPUT_ROOT
    hash_algorithm: str = "sha256"
    sample_bytes: int = 0
    ignore_patterns: List[str] = field(default_factory=list)
    follow_symlinks: bool = False
    max_files: Optional[int] = None

    def effective_ignore(self) -> List[str]:
        return DEFAULT_IGNORE + [p for p in (self.ignore_patterns or []) if p]

    def hash_enabled(self) -> bool:
        return self.hash_algorithm.lower() != "none"


@dataclass
class ProbePaths:
    inventory: Path
    outputs_root: Path = DEFAULT_OUTPUT_ROOT


@dataclass
class ProbeRunConfig:
    paths: ProbePaths
    text_char_threshold: int = 25
    doc_text_pct_text: float = 0.50
    doc_text_pct_scanned: float = 0.10
    doc_text_min_chars_per_page: int = 200
    fixed_black_intensity: int = 40
    mostly_black_ratio_fixed: float = 0.90
    adaptive_percentile: float = 10.0
    mostly_black_ratio_adapt: float = 0.90
    dark_page_median_cutoff: float = 90.0
    redaction_dark_ratio_min: float = 0.02
    redaction_contrast_min: float = 30.0
    redaction_low_contrast_max: float = 12.0
    render_dpi: int = 72
    center_crop_pct: float = 0.70
    use_center_crop: bool = True
    max_pdfs: int = 0
    max_pages: int = 0
    skip_black_check: bool = False
    skip_text_check: bool = False
    seed: int | None = None
    only_top_folder: str | None = None
    use_doc_type_model: bool = False
    doc_type_model_ref: str = ""
    min_model_confidence: float = 0.70

    @property
    def run_args(self) -> dict:
        data = self.__dict__.copy()
        data["paths"] = {
            "inventory": str(self.paths.inventory),
            "outputs_root": str(self.paths.outputs_root),
        }
        return data


def sanitize_run_label(value: str | None) -> str | None:
    if not value:
        return None
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "root"


def new_run_id(prefix: str, label: str | None = None) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sanitized_label = sanitize_run_label(label)
    if sanitized_label:
        return f"{sanitized_label}_{prefix}_{timestamp}"
    return f"{prefix}_{timestamp}"


__all__ = [
    "InventoryConfig",
    "ProbePaths",
    "ProbeRunConfig",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_DATA_ROOT",
    "DEFAULT_IGNORE",
    "sanitize_run_label",
    "new_run_id",
]
