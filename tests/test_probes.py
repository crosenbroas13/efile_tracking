import numpy as np
import pandas as pd
from PIL import Image

from pathlib import Path

from src.probe_config import ProbeConfig
from src.probe_blackpages import _black_ratio_from_image, compute_darkness_metrics
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
    config = ProbeConfig(inventory_path=Path("dummy"), output_root=Path("out"), fixed_black_intensity=10, center_crop_pct=0.5)
    metrics = _black_ratio_from_image(img.convert("RGB"), config)
    assert metrics["black_ratio_fixed_full"] == 0.9
    assert metrics["black_ratio_fixed_center"] == 1.0
    assert metrics["black_ratio_fixed"] == 1.0
    assert metrics["is_mostly_black"] is True


def test_darkness_metrics_scenarios():
    config = ProbeConfig(inventory_path=Path("dummy"), output_root=Path("out"))

    # 1) pure black page
    black = np.zeros((10, 10), dtype=np.uint8)
    metrics_black = compute_darkness_metrics(black, config)
    assert metrics_black["is_mostly_black"] is True
    assert metrics_black["black_ratio_fixed"] == 1.0

    # 2) mostly white with tiny black region (below redaction ratio threshold)
    white = np.full((10, 10), 255, dtype=np.uint8)
    white[0, 0] = 0
    metrics_white = compute_darkness_metrics(white, config)
    assert metrics_white["is_mostly_black"] is False

    # 3) page with redaction-like blocks (enough dark pixels + contrast)
    redaction_like = np.full((10, 10), 255, dtype=np.uint8)
    redaction_like[0:3, 0:3] = 0
    metrics_redaction = compute_darkness_metrics(redaction_like, config)
    assert metrics_redaction["is_mostly_black"] is True

    # 4) dark gray page flagged by low-contrast rule
    gray_dark = np.full((10, 10), 80, dtype=np.uint8)
    metrics_dark = compute_darkness_metrics(gray_dark, config)
    assert metrics_dark["is_mostly_black"] is True
    assert metrics_dark["black_ratio_fixed"] == 0.0
    assert metrics_dark["black_ratio_adapt"] == 1.0

    # 5) gradient page should not trigger
    gradient = np.linspace(50, 200, num=100, dtype=np.uint8).reshape((10, 10))
    metrics_grad = compute_darkness_metrics(gradient, config)
    assert metrics_grad["is_mostly_black"] is False

    # Deterministic adaptive threshold (ties fall back to full-page threshold)
    if metrics_grad["black_ratio_adapt_center"] >= metrics_grad["black_ratio_adapt_full"]:
        assert metrics_grad["black_threshold_adapt"] == metrics_grad["black_threshold_adapt_center"]
    else:
        assert metrics_grad["black_threshold_adapt"] == metrics_grad["black_threshold_adapt_full"]


def test_stable_doc_id_prefer_sha():
    row = pd.Series({"sha256": "abc", "rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row) == "abc"
    row_no_hash = pd.Series({"rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row_no_hash) == "file.pdf|10|2024"
