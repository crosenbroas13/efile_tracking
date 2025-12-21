import pandas as pd
from PIL import Image

from pathlib import Path

from src.probe_config import ProbeConfig
from src.probe_blackpages import _black_ratio_from_image
from src.probe_readiness import classify_document, stable_doc_id


def test_document_classification_thresholds():
    config = ProbeConfig(inventory_path=Path("dummy"), output_root=Path("out"))
    assert classify_document(0.95, config) == "Text-based"
    assert classify_document(0.05, config) == "Scanned"
    assert classify_document(0.5, config) == "Mixed"


def test_black_ratio_computation():
    img = Image.new("L", (10, 10), color=255)
    for x in range(9):
        for y in range(10):
            img.putpixel((x, y), 0)
    ratio = _black_ratio_from_image(
        img.convert("RGB"),
        full_mean_ceiling=60,
        full_high_pct=75,
        full_high_pct_ceiling=80,
        center_crop_pct=0.5,
        center_mean_ceiling=70,
        center_high_pct=75,
        center_high_pct_ceiling=90,
        use_center=True,
    )
    assert ratio == 1.0


def test_stable_doc_id_prefer_sha():
    row = pd.Series({"sha256": "abc", "rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row) == "abc"
    row_no_hash = pd.Series({"rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row_no_hash) == "file.pdf|10|2024"
