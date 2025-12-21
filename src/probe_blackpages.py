from __future__ import annotations

import importlib.util
import logging
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


def _luminance_stats(gray_array: np.ndarray, high_percentile: float) -> tuple[float, float]:
    mean_lum = float(np.mean(gray_array)) if gray_array.size else 0.0
    pct_value = float(np.percentile(gray_array, high_percentile)) if gray_array.size else 0.0
    return mean_lum, pct_value


def _black_ratio_from_image(
    img: Image.Image,
    *,
    full_mean_ceiling: float,
    full_high_pct: float,
    full_high_pct_ceiling: float,
    center_crop_pct: float,
    center_mean_ceiling: float,
    center_high_pct: float,
    center_high_pct_ceiling: float,
    use_center: bool,
) -> float:
    gray_array = np.asarray(img.convert("L"), dtype=np.float32)
    full_mean, full_high_pct_value = _luminance_stats(gray_array, full_high_pct)
    full_dark = full_mean <= full_mean_ceiling and full_high_pct_value <= full_high_pct_ceiling

    if not use_center:
        return 1.0 if full_dark else 0.0

    height, width = gray_array.shape
    crop_w = max(1, int(width * center_crop_pct))
    crop_h = max(1, int(height * center_crop_pct))
    start_x = max(0, (width - crop_w) // 2)
    start_y = max(0, (height - crop_h) // 2)
    center_array = gray_array[start_y : start_y + crop_h, start_x : start_x + crop_w]
    center_mean, center_high_pct_value = _luminance_stats(center_array, center_high_pct)
    center_dark = center_mean <= center_mean_ceiling and center_high_pct_value <= center_high_pct_ceiling

    return 1.0 if (full_dark or center_dark) else 0.0


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
            ratio = _black_ratio_from_image(
                img,
                full_mean_ceiling=config.full_mean_ceiling,
                full_high_pct=config.full_high_pct,
                full_high_pct_ceiling=config.full_high_pct_ceiling,
                center_crop_pct=config.center_crop_pct,
                center_mean_ceiling=config.center_mean_ceiling,
                center_high_pct=config.center_high_pct,
                center_high_pct_ceiling=config.center_high_pct_ceiling,
                use_center=config.use_center_crop,
            )
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
    "render_page",
    "evaluate_black_pages",
    "_black_ratio_from_image",
]
