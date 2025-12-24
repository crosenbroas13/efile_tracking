from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from ...utils.paths import normalize_rel_path
from ...utils.fitz_loader import load_fitz
from .constants import DEFAULT_DPI, DEFAULT_PAGES_SAMPLED, DEFAULT_SEED

fitz = load_fitz()

@dataclass(frozen=True)
class FeatureConfig:
    pages_sampled: int = DEFAULT_PAGES_SAMPLED
    dpi: int = DEFAULT_DPI
    seed: int = DEFAULT_SEED


def extract_doc_features(
    pdfs_df: pd.DataFrame,
    probe_docs: Optional[pd.DataFrame] = None,
    *,
    pages_sampled: int = DEFAULT_PAGES_SAMPLED,
    dpi: int = DEFAULT_DPI,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    pdfs_df = pdfs_df.copy()
    if "rel_path" in pdfs_df.columns:
        pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)
    if "probe_path" not in pdfs_df.columns:
        pdfs_df["probe_path"] = pdfs_df.get("abs_path")

    probe_metrics = _build_probe_metric_map(probe_docs)

    feature_rows: List[Dict[str, object]] = []
    for _, row in pdfs_df.iterrows():
        rel_path = str(row.get("rel_path") or "")
        probe_path = row.get("probe_path") or row.get("abs_path")
        doc_features = _extract_single_pdf_features(
            Path(str(probe_path)) if probe_path else None,
            rel_path,
            pages_sampled=pages_sampled,
            dpi=dpi,
            seed=seed,
        )
        metrics = probe_metrics.get(rel_path, {})
        feature_rows.append(
            {
                "rel_path": rel_path,
                "doc_id": row.get("doc_id", ""),
                "top_level_folder": row.get("top_level_folder", ""),
                "pages_sampled": doc_features.pop("pages_sampled", 0),
                "dpi": doc_features.pop("dpi", dpi),
                "seed": seed,
                **metrics,
                **doc_features,
            }
        )

    return pd.DataFrame(feature_rows)


def _build_probe_metric_map(probe_docs: Optional[pd.DataFrame]) -> Dict[str, Dict[str, float]]:
    if probe_docs is None or probe_docs.empty:
        return {}
    probe_docs = probe_docs.copy()
    if "rel_path" in probe_docs.columns:
        probe_docs["rel_path"] = probe_docs["rel_path"].astype(str).map(normalize_rel_path)
    metrics = {}
    for _, row in probe_docs.iterrows():
        rel_path = str(row.get("rel_path") or "")
        if not rel_path:
            continue
        metrics[rel_path] = {
            "page_count": _safe_numeric(row.get("page_count")),
            "pages_with_text": _safe_numeric(row.get("pages_with_text")),
            "text_coverage_pct": _safe_numeric(row.get("text_coverage_pct")),
            "avg_text_chars_per_page": _safe_numeric(row.get("avg_text_chars_per_page")),
            "mostly_black_pct": _safe_numeric(row.get("mostly_black_pct"))
            if "mostly_black_pct" in probe_docs.columns
            else math.nan,
        }
    return metrics


def _extract_single_pdf_features(
    path: Optional[Path],
    rel_path: str,
    *,
    pages_sampled: int,
    dpi: int,
    seed: int,
) -> Dict[str, float]:
    if path is None or not path.exists():
        return _empty_feature_payload(pages_sampled, dpi)
    try:
        doc = fitz.open(path)
    except Exception:
        return _empty_feature_payload(pages_sampled, dpi)

    page_count = doc.page_count
    if page_count <= 0:
        doc.close()
        return _empty_feature_payload(pages_sampled, dpi)

    sample_indices = _sample_pages(page_count, pages_sampled, seed, rel_path)
    per_page_features: Dict[str, List[float]] = {}
    for page_index in sample_indices:
        try:
            page = doc.load_page(page_index)
        except Exception:
            continue
        page_features = _extract_page_features(page, dpi)
        for key, value in page_features.items():
            per_page_features.setdefault(key, []).append(value)
    doc.close()

    aggregated = _aggregate_page_features(per_page_features)
    aggregated.update({"pages_sampled": len(sample_indices), "dpi": dpi})
    return aggregated


def _empty_feature_payload(pages_sampled: int, dpi: int) -> Dict[str, float]:
    payload = {
        "pages_sampled": 0,
        "dpi": dpi,
    }
    for key in _PAGE_FEATURE_KEYS():
        payload[f"{key}_mean"] = math.nan
        payload[f"{key}_median"] = math.nan
    payload.update(
        {
            "font_present_pct": math.nan,
            "avg_font_count": math.nan,
            "image_present_pct": math.nan,
            "avg_image_count": math.nan,
            "font_present_median": math.nan,
            "font_count_median": math.nan,
            "image_present_median": math.nan,
            "image_count_median": math.nan,
        }
    )
    return payload


def _sample_pages(page_count: int, pages_sampled: int, seed: int, rel_path: str) -> List[int]:
    total = max(1, min(page_count, pages_sampled))
    if total >= page_count:
        return list(range(page_count))
    digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16)
    rng = random.Random(seed + offset)
    return sorted(rng.sample(range(page_count), total))


def _extract_page_features(page: fitz.Page, dpi: int) -> Dict[str, float]:
    fonts = page.get_fonts() or []
    images = page.get_images(full=True) or []
    font_count = float(len(fonts))
    image_count = float(len(images))

    gray = _render_page_gray(page, dpi)
    if gray is None:
        return {
            "font_present": float(font_count > 0),
            "font_count": font_count,
            "image_present": float(image_count > 0),
            "image_count": image_count,
        }
    gray_stats = _gray_statistics(gray)
    entropy = _histogram_entropy(gray)
    edge_density = _sobel_edge_density(gray)
    otsu_t = _otsu_threshold(gray)
    binarized = (gray <= otsu_t).astype(np.uint8)
    binarized_ratio = float(binarized.mean())
    projection_var_row, projection_var_col = projection_variance(binarized)

    features = {
        "font_present": float(font_count > 0),
        "font_count": font_count,
        "image_present": float(image_count > 0),
        "image_count": image_count,
        "gray_mean": gray_stats["mean"],
        "gray_std": gray_stats["std"],
        "gray_median": gray_stats["median"],
        "gray_p10": gray_stats["p10"],
        "gray_p90": gray_stats["p90"],
        "histogram_entropy": entropy,
        "edge_density": edge_density,
        "otsu_threshold": float(otsu_t),
        "binarized_ratio": binarized_ratio,
        "projection_var_row": projection_var_row,
        "projection_var_col": projection_var_col,
    }
    return features


def _render_page_gray(page: fitz.Page, dpi: int) -> Optional[np.ndarray]:
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    except Exception:
        return None
    if pix.width == 0 or pix.height == 0:
        return None
    gray = np.frombuffer(pix.samples, dtype=np.uint8)
    gray = gray.reshape(pix.height, pix.width)
    return gray


def _gray_statistics(gray: np.ndarray) -> Dict[str, float]:
    return {
        "mean": float(np.mean(gray)),
        "std": float(np.std(gray)),
        "median": float(np.median(gray)),
        "p10": float(np.percentile(gray, 10)),
        "p90": float(np.percentile(gray, 90)),
    }


def _histogram_entropy(gray: np.ndarray) -> float:
    hist = np.histogram(gray, bins=256, range=(0, 255))[0].astype(float)
    total = hist.sum()
    if total == 0:
        return math.nan
    probs = hist / total
    nonzero = probs[probs > 0]
    return float(-(nonzero * np.log2(nonzero)).sum())


def _sobel_edge_density(gray: np.ndarray, threshold: float = 50.0) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return math.nan
    gray = gray.astype(float)
    gx = (
        gray[:-2, 2:]
        + 2 * gray[1:-1, 2:]
        + gray[2:, 2:]
        - gray[:-2, :-2]
        - 2 * gray[1:-1, :-2]
        - gray[2:, :-2]
    )
    gy = (
        gray[2:, :-2]
        + 2 * gray[2:, 1:-1]
        + gray[2:, 2:]
        - gray[:-2, :-2]
        - 2 * gray[:-2, 1:-1]
        - gray[:-2, 2:]
    )
    magnitude = np.hypot(gx, gy)
    return float(np.mean(magnitude > threshold))


def _otsu_threshold(gray: np.ndarray) -> int:
    hist = np.histogram(gray, bins=256, range=(0, 255))[0].astype(float)
    total = gray.size
    if total == 0:
        return 0
    sum_total = float(np.dot(np.arange(256), hist))
    sum_bg = 0.0
    weight_bg = 0.0
    max_var = -1.0
    threshold = 0
    for i in range(256):
        weight_bg += hist[i]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += i * hist[i]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = i
    return threshold


def projection_variance(binarized: np.ndarray) -> tuple[float, float]:
    if binarized.size == 0:
        return math.nan, math.nan
    row_sum = binarized.sum(axis=1)
    col_sum = binarized.sum(axis=0)
    return float(np.var(row_sum)), float(np.var(col_sum))


def _aggregate_page_features(per_page_features: Dict[str, List[float]]) -> Dict[str, float]:
    aggregated: Dict[str, float] = {}
    for key in _PAGE_FEATURE_KEYS():
        values = per_page_features.get(key, [])
        aggregated[f"{key}_mean"] = _nan_mean(values)
        aggregated[f"{key}_median"] = _nan_median(values)
    aggregated["font_present_pct"] = aggregated.get("font_present_mean", math.nan)
    aggregated["avg_font_count"] = aggregated.get("font_count_mean", math.nan)
    aggregated["image_present_pct"] = aggregated.get("image_present_mean", math.nan)
    aggregated["avg_image_count"] = aggregated.get("image_count_mean", math.nan)
    return aggregated


def _PAGE_FEATURE_KEYS() -> List[str]:
    return [
        "font_present",
        "font_count",
        "image_present",
        "image_count",
        "gray_mean",
        "gray_std",
        "gray_median",
        "gray_p10",
        "gray_p90",
        "histogram_entropy",
        "edge_density",
        "otsu_threshold",
        "binarized_ratio",
        "projection_var_row",
        "projection_var_col",
    ]


def _nan_mean(values: Iterable[float]) -> float:
    if not values:
        return math.nan
    arr = np.array(list(values), dtype=float)
    if np.isnan(arr).all():
        return math.nan
    return float(np.nanmean(arr))


def _nan_median(values: Iterable[float]) -> float:
    if not values:
        return math.nan
    arr = np.array(list(values), dtype=float)
    if np.isnan(arr).all():
        return math.nan
    return float(np.nanmedian(arr))


def _safe_numeric(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


__all__ = [
    "DEFAULT_PAGES_SAMPLED",
    "DEFAULT_DPI",
    "DEFAULT_SEED",
    "FeatureConfig",
    "extract_doc_features",
    "projection_variance",
]
