from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from src.probe_blackpages import evaluate_black_pages
from src.probe_readiness import evaluate_readiness, list_pdfs

from ..config import ProbeRunConfig, ProbePaths
from ..utils.io import ensure_dir
from .outputs import write_probe_outputs


def run_probe(config: ProbeRunConfig) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    start_time = time.time()
    pdfs, ignored_counts, ignored_mime_counts = list_pdfs(
        config.paths.inventory,
        config.only_top_folder,
        extract_root=config.paths.outputs_root,
    )

    text_pages = pd.DataFrame()
    text_docs = pd.DataFrame()
    text_errors: List[Dict] = []
    if not config.skip_text_check:
        text_pages, text_docs, text_errors = evaluate_readiness(pdfs, config)

    black_pages = pd.DataFrame()
    black_docs = pd.DataFrame()
    black_errors: List[Dict] = []
    if not config.skip_black_check:
        black_pages, black_docs, black_errors = evaluate_black_pages(pdfs, text_pages, config)

    pages_df = black_pages if not config.skip_black_check else text_pages
    if config.skip_black_check and not pages_df.empty:
        for col in [
            "black_ratio",
            "black_ratio_full",
            "black_ratio_center",
            "adaptive_black_ratio",
            "adaptive_black_ratio_full",
            "adaptive_black_ratio_center",
            "black_threshold_adapt",
            "gray_mean",
            "gray_median",
            "gray_p10",
            "gray_p25",
            "gray_p75",
            "gray_std",
            "is_mostly_black",
        ]:
            if col not in pages_df.columns:
                pages_df[col] = None

    base_docs = pdfs[["doc_id", "rel_path", "abs_path", "top_level_folder"]].copy()
    if not text_docs.empty:
        base_docs = base_docs.merge(
            text_docs.drop(columns=["rel_path", "abs_path", "top_level_folder"]), on="doc_id", how="left"
        )
    if not black_docs.empty:
        base_docs = base_docs.merge(
            black_docs.drop(columns=["rel_path", "abs_path", "top_level_folder"]),
            on="doc_id",
            how="left",
            suffixes=("", "_black"),
        )
        base_docs["pages_mostly_black"] = base_docs.get("pages_mostly_black")
        base_docs["mostly_black_pct"] = base_docs.get("mostly_black_pct")
        base_docs["black_ratio_avg"] = base_docs.get("black_ratio_avg")
    for col, default in [
        ("page_count", 0),
        ("pages_with_text", 0),
        ("text_coverage_pct", 0.0),
        ("pages_mostly_black", 0),
        ("mostly_black_pct", 0.0),
        ("black_ratio_avg", 0.0),
        ("notes", ""),
    ]:
        if col not in base_docs.columns:
            base_docs[col] = default
    if "classification" not in base_docs.columns:
        base_docs["classification"] = "Unknown"
    docs_df = base_docs

    all_errors = text_errors + black_errors
    runtime = time.time() - start_time
    meta = {
        "probe_run_seconds": runtime,
        "error_count": len(all_errors),
        "errors": all_errors,
        "errors_sample": all_errors[:20],
        "ignored_non_pdf_files": ignored_counts,
        "ignored_non_pdf_mime_types": ignored_mime_counts,
        "ignored_non_pdf_total": int(sum(ignored_counts.values())),
    }
    return pages_df, docs_df, meta


def run_probe_and_save(config: ProbeRunConfig) -> Path:
    ensure_dir(config.paths.outputs_root)
    pages_df, docs_df, meta = run_probe(config)
    return write_probe_outputs(pages_df, docs_df, config, meta)


__all__ = ["run_probe", "run_probe_and_save"]
