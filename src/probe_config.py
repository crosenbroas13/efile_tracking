from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProbeConfig:
    inventory_path: Path
    output_root: Path
    text_char_threshold: int = 25
    doc_text_pct_text: float = 0.90
    doc_text_pct_scanned: float = 0.10
    mostly_black_ratio: float = 0.90
    full_mean_ceiling: float = 60.0
    full_high_pct: float = 75.0
    full_high_pct_ceiling: float = 80.0
    center_mean_ceiling: float = 70.0
    center_high_pct: float = 75.0
    center_high_pct_ceiling: float = 90.0
    render_dpi: int = 72
    center_crop_pct: float = 0.70
    use_center_crop: bool = True
    max_pdfs: int = 0
    max_pages: int = 0
    skip_black_check: bool = False
    skip_text_check: bool = False
    seed: int | None = None
    only_top_folder: str | None = None

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["inventory_path"] = str(self.inventory_path)
        data["output_root"] = str(self.output_root)
        return data
