from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import importlib.util

import numpy as np
import pandas as pd
from PIL import Image

from src.doj_doc_explorer.utils.fitz_loader import load_fitz_optional

fitz = load_fitz_optional()

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
    ratio_fixed_full: float
    ratio_fixed_center: float
    ratio_adapt_full: float
    ratio_adapt_center: float
    gray_mean: float
    gray_median: float
    gray_p10: float
    gray_p25: float
    gray_p75: float
    gray_std: float
    threshold_adapt_full: float
    threshold_adapt_center: float

    @property
    def ratio_fixed(self) -> float:
        return max(self.ratio_fixed_full, self.ratio_fixed_center)

    @property
    def ratio_adapt(self) -> float:
        return max(self.ratio_adapt_full, self.ratio_adapt_center)

    @property
    def threshold_adapt(self) -> float:
        return (
            self.threshold_adapt_center
            if self.ratio_adapt_center >= self.ratio_adapt_full
            else self.threshold_adapt_full
        )


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


def _center_crop(gray_array: np.ndarray, center_crop_pct: float) -> np.ndarray:
    height, width = gray_array.shape
    crop_w = max(1, int(width * center_crop_pct))
    crop_h = max(1, int(height * center_crop_pct))
    start_x = max(0, (width - crop_w) // 2)
    start_y = max(0, (height - crop_h) // 2)
    return gray_array[start_y : start_y + crop_h, start_x : start_x + crop_w]


def _ratio_leq(gray_flat: np.ndarray, threshold: float) -> float:
    if gray_flat.size == 0:
        return 0.0
    threshold_index = int(np.floor(threshold))
    hist = np.bincount(gray_flat, minlength=256)
    count = hist[: threshold_index + 1].sum()
    return float(count / gray_flat.size)


def compute_darkness_metrics(gray_array: np.ndarray, config: ProbeConfig) -> Dict:
    gray = np.asarray(gray_array, dtype=np.uint8)
    flat = gray.reshape(-1)
    total_pixels = flat.size
    if total_pixels == 0:
        return {
            "gray_mean": 0.0,
            "gray_median": 0.0,
            "gray_p10": 0.0,
            "gray_p25": 0.0,
            "gray_p75": 0.0,
            "gray_std": 0.0,
            "black_ratio_fixed_full": 0.0,
            "black_ratio_fixed_center": 0.0,
            "black_ratio_fixed": 0.0,
            "black_ratio_adapt_full": 0.0,
            "black_ratio_adapt_center": 0.0,
            "black_ratio_adapt": 0.0,
            "black_threshold_adapt_full": 0.0,
            "black_threshold_adapt_center": 0.0,
            "black_threshold_adapt": 0.0,
            "is_mostly_black": False,
        }

    gray_mean = float(gray.mean())
    gray_std = float(gray.std())
    gray_median = float(np.median(flat))
    gray_p10 = float(np.percentile(flat, 10))
    gray_p25 = float(np.percentile(flat, 25))
    gray_p75 = float(np.percentile(flat, 75))

    t_adapt_full = float(np.percentile(flat, config.adaptive_percentile))
    ratio_fixed_full = _ratio_leq(flat, config.fixed_black_intensity)
    ratio_adapt_full = _ratio_leq(flat, t_adapt_full)

    ratio_fixed_center = 0.0
    ratio_adapt_center = 0.0
    t_adapt_center = 0.0
    if config.use_center_crop:
        crop = _center_crop(gray, config.center_crop_pct)
        crop_flat = crop.reshape(-1)
        t_adapt_center = float(np.percentile(crop_flat, config.adaptive_percentile)) if crop_flat.size else 0.0
        ratio_fixed_center = _ratio_leq(crop_flat, config.fixed_black_intensity) if crop_flat.size else 0.0
        ratio_adapt_center = _ratio_leq(crop_flat, t_adapt_center) if crop_flat.size else 0.0

    ratio_fixed = max(ratio_fixed_full, ratio_fixed_center)
    ratio_adapt = max(ratio_adapt_full, ratio_adapt_center)
    threshold_adapt = t_adapt_center if ratio_adapt_center >= ratio_adapt_full else t_adapt_full

    is_mostly_black = bool(
        (ratio_fixed >= config.mostly_black_ratio_fixed)
        or (
            ratio_fixed >= config.redaction_dark_ratio_min
            and gray_std >= config.redaction_contrast_min
        )
        or (
            gray_median <= config.dark_page_median_cutoff
            and gray_std <= config.redaction_low_contrast_max
        )
    )

    metrics = BlackPageMetrics(
        ratio_fixed_full=ratio_fixed_full,
        ratio_fixed_center=ratio_fixed_center,
        ratio_adapt_full=ratio_adapt_full,
        ratio_adapt_center=ratio_adapt_center,
        gray_mean=gray_mean,
        gray_median=gray_median,
        gray_p10=gray_p10,
        gray_p25=gray_p25,
        gray_p75=gray_p75,
        gray_std=gray_std,
        threshold_adapt_full=t_adapt_full,
        threshold_adapt_center=t_adapt_center,
    )

    return {
        "gray_mean": metrics.gray_mean,
        "gray_median": metrics.gray_median,
        "gray_p10": metrics.gray_p10,
        "gray_p25": metrics.gray_p25,
        "gray_p75": metrics.gray_p75,
        "gray_std": metrics.gray_std,
        "black_ratio_fixed_full": metrics.ratio_fixed_full,
        "black_ratio_fixed_center": metrics.ratio_fixed_center,
        "black_ratio_fixed": metrics.ratio_fixed,
        "black_ratio_adapt_full": metrics.ratio_adapt_full,
        "black_ratio_adapt_center": metrics.ratio_adapt_center,
        "black_ratio_adapt": metrics.ratio_adapt,
        "black_threshold_adapt_full": metrics.threshold_adapt_full,
        "black_threshold_adapt_center": metrics.threshold_adapt_center,
        "black_threshold_adapt": metrics.threshold_adapt,
        "is_mostly_black": is_mostly_black,
    }


def _black_ratio_from_image(
    img: Image.Image, config: ProbeConfig
) -> Dict:
    gray_array = np.asarray(img.convert("L"), dtype=np.uint8)
    return compute_darkness_metrics(gray_array, config)


def evaluate_black_pages(
    pdfs: pd.DataFrame,
    pages_df: pd.DataFrame,
    config: ProbeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
    records: List[Dict] = []
    doc_records: Dict[str, Dict] = {
        row.doc_id: {
            "pages_mostly_black": 0,
            "page_count": 0,
            "pages_black_checked": 0,
            "ratios": [],
            "gray_medians": [],
        }
        for row in pdfs.itertuples()
    }
    errors: List[Dict] = []

    page_lookup = pages_df.set_index(["doc_id", "page_num"]) if not pages_df.empty else None

    for row in pdfs.itertuples(index=False):
        probe_path = getattr(row, "probe_path", None) or row.abs_path
        if not probe_path:
            errors.append({"doc_id": row.doc_id, "path": row.abs_path, "errors": ["Probe path missing for PDF"]})
            continue
        doc_path = Path(probe_path)
        if not doc_path.exists():
            errors.append({"doc_id": row.doc_id, "path": row.abs_path, "errors": [f"Probe path does not exist: {doc_path}"]})
            continue
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
                metrics_dict = {
                    "gray_mean": None,
                    "gray_median": None,
                    "gray_p10": None,
                    "gray_p25": None,
                    "gray_p75": None,
                    "gray_std": None,
                    "black_ratio_fixed_full": None,
                    "black_ratio_fixed_center": None,
                    "black_ratio_fixed": None,
                    "black_ratio_adapt_full": None,
                    "black_ratio_adapt_center": None,
                    "black_ratio_adapt": None,
                    "black_threshold_adapt_full": None,
                    "black_threshold_adapt_center": None,
                    "black_threshold_adapt": None,
                    "is_mostly_black": None,
                }
            else:
                metrics_dict = _black_ratio_from_image(img, config)
            ratio = metrics_dict.get("black_ratio_fixed") or 0.0
            is_black_value = metrics_dict.get("is_mostly_black")
            is_black = bool(is_black_value)
            has_black_metrics = is_black_value is not None
            base_record = {
                "doc_id": row.doc_id,
                "rel_path": getattr(row, "rel_path", None),
                "abs_path": row.abs_path,
                "top_level_folder": getattr(row, "top_level_folder", None),
                "page_num": idx + 1,
                "text_char_count": None,
                "has_text": None,
                "black_ratio": metrics_dict.get("black_ratio_fixed"),
                "black_ratio_full": metrics_dict.get("black_ratio_fixed_full"),
                "black_ratio_center": metrics_dict.get("black_ratio_fixed_center"),
                "adaptive_black_ratio": metrics_dict.get("black_ratio_adapt"),
                "adaptive_black_ratio_full": metrics_dict.get("black_ratio_adapt_full"),
                "adaptive_black_ratio_center": metrics_dict.get("black_ratio_adapt_center"),
                "black_threshold_adapt": metrics_dict.get("black_threshold_adapt"),
                "gray_mean": metrics_dict.get("gray_mean"),
                "gray_median": metrics_dict.get("gray_median"),
                "gray_p10": metrics_dict.get("gray_p10"),
                "gray_p25": metrics_dict.get("gray_p25"),
                "gray_p75": metrics_dict.get("gray_p75"),
                "gray_std": metrics_dict.get("gray_std"),
                "is_mostly_black": metrics_dict.get("is_mostly_black"),
            }
            if page_lookup is not None and (row.doc_id, idx + 1) in page_lookup.index:
                merged = base_record | page_lookup.loc[(row.doc_id, idx + 1)].to_dict()
                records.append(merged)
            else:
                records.append(base_record)
            doc_records[row.doc_id]["page_count"] += 1
            if has_black_metrics:
                doc_records[row.doc_id]["pages_black_checked"] += 1
            if metrics_dict.get("black_ratio_fixed") is not None:
                doc_records[row.doc_id]["ratios"].append(metrics_dict.get("black_ratio_fixed") or 0.0)
            if metrics_dict.get("gray_median") is not None:
                doc_records[row.doc_id]["gray_medians"].append(metrics_dict.get("gray_median") or 0.0)
            if is_black:
                doc_records[row.doc_id]["pages_mostly_black"] += 1

    doc_rows: List[Dict] = []
    for row in pdfs.itertuples(index=False):
        doc_entry = doc_records.get(
            row.doc_id,
            {"pages_mostly_black": 0, "page_count": 0, "pages_black_checked": 0, "ratios": [], "gray_medians": []},
        )
        page_count = doc_entry["page_count"]
        mostly_black = doc_entry["pages_mostly_black"]
        pages_black_checked = doc_entry.get("pages_black_checked", 0)
        ratio_list = doc_entry["ratios"]
        median_list = doc_entry.get("gray_medians", [])
        avg_gray_median = sum(median_list) / len(median_list) if median_list else 0
        p50_gray_median = float(np.median(median_list)) if median_list else 0
        doc_rows.append(
            {
                "doc_id": row.doc_id,
                "rel_path": getattr(row, "rel_path", None),
                "abs_path": row.abs_path,
                "top_level_folder": getattr(row, "top_level_folder", None),
                "page_count": page_count,
                "pages_black_checked": pages_black_checked,
                "pages_mostly_black": mostly_black,
                "mostly_black_pct": (mostly_black / pages_black_checked) if pages_black_checked else None,
                "black_ratio_avg": sum(ratio_list) / len(ratio_list) if ratio_list else 0,
                "gray_median_avg": avg_gray_median,
                "gray_median_p50": p50_gray_median,
            }
        )

    return pd.DataFrame(records), pd.DataFrame(doc_rows), errors


__all__ = [
    "BlackPageMetrics",
    "render_page",
    "evaluate_black_pages",
    "_black_ratio_from_image",
    "compute_darkness_metrics",
]
