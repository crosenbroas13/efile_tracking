from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
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


def _black_ratio_from_image(img: Image.Image, black_intensity: int, center_crop_pct: float, use_center: bool) -> float:
    gray = img.convert("L")
    pixels = gray.load()
    width, height = gray.size
    total_pixels = width * height
    black_pixels = 0
    for x in range(width):
        for y in range(height):
            if pixels[x, y] <= black_intensity:
                black_pixels += 1
    full_ratio = black_pixels / total_pixels if total_pixels else 0

    if not use_center:
        return full_ratio

    crop_w = int(width * center_crop_pct)
    crop_h = int(height * center_crop_pct)
    start_x = (width - crop_w) // 2
    start_y = (height - crop_h) // 2
    crop = gray.crop((start_x, start_y, start_x + crop_w, start_y + crop_h))
    crop_pixels = crop.load()
    crop_total = crop_w * crop_h
    crop_black = 0
    for x in range(crop_w):
        for y in range(crop_h):
            if crop_pixels[x, y] <= black_intensity:
                crop_black += 1
    crop_ratio = crop_black / crop_total if crop_total else 0
    return max(full_ratio, crop_ratio)


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
                black_intensity=config.black_threshold_intensity,
                center_crop_pct=config.center_crop_pct,
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
