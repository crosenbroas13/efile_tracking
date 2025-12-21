from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
import numpy as np
from PIL import Image

_fitz_spec = importlib.util.find_spec("fitz")
if _fitz_spec:  # pragma: no cover - optional import
    import importlib

    fitz = importlib.import_module("fitz")  # type: ignore
else:  # pragma: no cover - optional import
    fitz = None

_pdf2image_spec = importlib.util.find_spec("pdf2image")
if _pdf2image_spec:  # pragma: no cover - optional import
    import importlib

    convert_from_path = importlib.import_module("pdf2image").convert_from_path  # type: ignore
else:  # pragma: no cover - optional import
    convert_from_path = None

from src.probe_config import ProbeConfig

LOGGER = logging.getLogger(__name__)


@dataclass
class BlackPageMetrics:
    full_ratio: float
    center_ratio: float
    adaptive_full_ratio: float
    adaptive_center_ratio: float
    mean_luminance: float
    std_luminance: float

    @property
    def dominant_ratio(self) -> float:
        """Highest darkness signal from absolute, adaptive, and crop checks."""

        return max(
            self.full_ratio,
            self.center_ratio,
            self.adaptive_full_ratio,
            self.adaptive_center_ratio,
            self._mean_darkness_signal(),
        )

    def _mean_darkness_signal(self) -> float:
        """Use mean luminance as a gentle fallback for low-contrast dark pages."""

        if self.std_luminance < 25:
            return max(0.0, min(1.0, 1 - (self.mean_luminance / 255)))
        return 0.0


def _pixmap_to_image(pixmap) -> Image.Image:
    mode = "RGBA" if pixmap.alpha else "RGB"
    return Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)


def render_page(path: Path, page_index: int, dpi: int = 72) -> Image.Image | None:
    if fitz:
        try:
            doc = fitz.open(str(path))
            page = doc.load_page(page_index)
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = _pixmap_to_image(pix).convert("RGB")
            doc.close()
            return img
        except Exception as exc:  # pragma: no cover - runtime safety
            LOGGER.warning("fitz render failed for %s page %s: %s", path, page_index, exc)
    if convert_from_path:
        try:
            images = convert_from_path(str(path), dpi=dpi, first_page=page_index + 1, last_page=page_index + 1)
            return images[0].convert("RGB")
        except Exception as exc:  # pragma: no cover - runtime safety
            LOGGER.warning("pdf2image render failed for %s page %s: %s", path, page_index, exc)
    return None


def _black_ratio_from_image(
    img: Image.Image, black_intensity: int, center_crop_pct: float, use_center: bool
) -> BlackPageMetrics:
    gray_array = np.asarray(img.convert("L"), dtype=np.uint8)
    total_pixels = gray_array.size
    mean_luminance = float(gray_array.mean()) if total_pixels else 0.0
    std_luminance = float(gray_array.std()) if total_pixels else 0.0

    absolute_mask = gray_array <= black_intensity
    full_ratio = float(absolute_mask.mean()) if total_pixels else 0.0

    adaptive_cutoff = min(black_intensity + 30, max(0.0, mean_luminance - std_luminance))
    adaptive_mask = gray_array <= adaptive_cutoff
    adaptive_full_ratio = float(adaptive_mask.mean()) if total_pixels else 0.0

    center_ratio = 0.0
    adaptive_center_ratio = 0.0
    if use_center:
        height, width = gray_array.shape
        crop_w = int(width * center_crop_pct)
        crop_h = int(height * center_crop_pct)
        start_x = (width - crop_w) // 2
        start_y = (height - crop_h) // 2
        crop = gray_array[start_y : start_y + crop_h, start_x : start_x + crop_w]
        crop_size = crop.size
        if crop_size:
            center_ratio = float((crop <= black_intensity).mean())
            adaptive_center_ratio = float((crop <= adaptive_cutoff).mean())

    return BlackPageMetrics(
        full_ratio=full_ratio,
        center_ratio=center_ratio,
        adaptive_full_ratio=adaptive_full_ratio,
        adaptive_center_ratio=adaptive_center_ratio,
        mean_luminance=mean_luminance,
        std_luminance=std_luminance,
    )


def evaluate_black_pages(
    pdfs: pd.DataFrame,
    pages_df: pd.DataFrame,
    config: ProbeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
    records: List[Dict] = []
    doc_records: Dict[str, Dict] = {
        row.doc_id: {"pages_mostly_black": 0, "page_count": 0, "ratios": []} for row in pdfs.itertuples()
    }
    errors: List[Dict] = []

    page_lookup = pages_df.set_index(["doc_id", "page_num"]) if not pages_df.empty else None

    for row in pdfs.itertuples(index=False):
        doc_path = Path(row.abs_path)
        try:
            page_total = row.page_count if hasattr(row, "page_count") and row.page_count else None
        except Exception:
            page_total = None
        page_total = page_total or getattr(row, "page_total", None)
        if page_lookup is not None:
            doc_pages = page_lookup.loc[row.doc_id] if row.doc_id in page_lookup.index.get_level_values(0) else None
            if doc_pages is not None:
                if hasattr(doc_pages, "index"):
                    page_total = max(page_total or 0, int(doc_pages.index.max())) if not isinstance(doc_pages, dict) else page_total
        if not page_total:
            try:
                if fitz:
                    with fitz.open(str(doc_path)) as doc:
                        page_total = len(doc)
                else:
                    with open(doc_path, "rb"):
                        page_total = None
            except Exception as exc:  # pragma: no cover
                errors.append({"doc_id": row.doc_id, "path": row.abs_path, "errors": [str(exc)]})
                continue
        if not page_total:
            errors.append({"doc_id": row.doc_id, "path": row.abs_path, "errors": ["Page count unavailable"]})
            continue
        pages_to_process = page_total if config.max_pages <= 0 else min(config.max_pages, page_total)
        for idx in range(pages_to_process):
            img = render_page(doc_path, idx, dpi=config.render_dpi)
            if img is None:
                errors.append(
                    {
                        "doc_id": row.doc_id,
                        "path": row.abs_path,
                        "errors": [f"Failed to render page {idx+1}"],
                    }
                )
                continue
            metrics = _black_ratio_from_image(
                img,
                black_intensity=config.black_threshold_intensity,
                center_crop_pct=config.center_crop_pct,
                use_center=config.use_center_crop,
            )
            ratio = metrics.dominant_ratio
            is_black = ratio >= config.mostly_black_ratio
            base_record = {
                "doc_id": row.doc_id,
                "rel_path": getattr(row, "rel_path", None),
                "abs_path": row.abs_path,
                "top_level_folder": getattr(row, "top_level_folder", None),
                "page_num": idx + 1,
                "text_char_count": None,
                "has_text": None,
                "black_ratio": ratio,
                "black_ratio_full": metrics.full_ratio,
                "black_ratio_center": metrics.center_ratio,
                "adaptive_black_ratio": metrics.adaptive_full_ratio,
                "adaptive_black_ratio_center": metrics.adaptive_center_ratio,
                "mean_luminance": metrics.mean_luminance,
                "std_luminance": metrics.std_luminance,
                "is_mostly_black": is_black,
            }
            if page_lookup is not None and (row.doc_id, idx + 1) in page_lookup.index:
                merged = base_record | page_lookup.loc[(row.doc_id, idx + 1)].to_dict()
                records.append(merged)
            else:
                records.append(base_record)
            doc_records[row.doc_id]["page_count"] += 1
            doc_records[row.doc_id]["ratios"].append(ratio)
            if is_black:
                doc_records[row.doc_id]["pages_mostly_black"] += 1

    doc_rows: List[Dict] = []
    for row in pdfs.itertuples(index=False):
        doc_entry = doc_records.get(row.doc_id, {"pages_mostly_black": 0, "page_count": 0, "ratios": []})
        page_count = doc_entry["page_count"]
        mostly_black = doc_entry["pages_mostly_black"]
        ratio_list = doc_entry["ratios"]
        doc_rows.append(
            {
                "doc_id": row.doc_id,
                "rel_path": getattr(row, "rel_path", None),
                "abs_path": row.abs_path,
                "top_level_folder": getattr(row, "top_level_folder", None),
                "page_count": page_count,
                "pages_mostly_black": mostly_black,
                "mostly_black_pct": (mostly_black / page_count) if page_count else 0,
                "black_ratio_avg": sum(ratio_list) / len(ratio_list) if ratio_list else 0,
            }
        )

    return pd.DataFrame(records), pd.DataFrame(doc_rows), errors


__all__ = [
    "BlackPageMetrics",
    "render_page",
    "evaluate_black_pages",
    "_black_ratio_from_image",
]
