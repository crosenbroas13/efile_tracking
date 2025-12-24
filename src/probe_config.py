from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProbeConfig:
    inventory_path: Path
    output_root: Path
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

    @property
    def black_threshold_intensity(self) -> int:
        """Backward-compatible alias for deprecated name."""

        return self.fixed_black_intensity

    @property
    def mostly_black_ratio(self) -> float:
        """Backward-compatible alias for deprecated name."""

        return self.mostly_black_ratio_fixed

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["inventory_path"] = str(self.inventory_path)
        data["output_root"] = str(self.output_root)
        return data
