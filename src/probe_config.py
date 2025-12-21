from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProbeConfig:
    inventory_path: Path
    output_root: Path
    text_char_threshold: int = 25
    doc_text_pct_text: float = 0.90
    doc_text_pct_scanned: float = 0.10
    black_threshold_intensity: int = 40
    mostly_black_ratio: float = 0.90
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
