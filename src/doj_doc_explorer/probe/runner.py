from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from src.probe_readiness import evaluate_readiness, list_pdfs

from ..config import ProbeRunConfig, ProbePaths
from ..classification.doc_type.model import apply_doc_type_decision, load_doc_type_model, predict_doc_types
from ..classification.doc_type.features import DEFAULT_DPI, DEFAULT_PAGES_SAMPLED, DEFAULT_SEED
from ..pdf_type.labels import labels_path, load_labels, match_labels_to_inventory
from ..utils.paths import normalize_rel_path
from ..utils.io import ensure_dir
from ..text_scan.io import load_latest_text_scan, merge_text_scan_signals
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

    pages_df = text_pages

    base_docs = pdfs[["doc_id", "rel_path", "abs_path", "top_level_folder"]].copy()
    if not text_docs.empty:
        base_docs = base_docs.merge(
            text_docs.drop(columns=["rel_path", "abs_path", "top_level_folder"]), on="doc_id", how="left"
        )
    for col, default in [
        ("page_count", 0),
        ("pages_with_text", 0),
        ("text_coverage_pct", 0.0),
        ("notes", ""),
    ]:
        if col not in base_docs.columns:
            base_docs[col] = default
    if "classification" not in base_docs.columns:
        base_docs["classification"] = "Unknown"
    docs_df = base_docs

    all_errors = text_errors
    runtime = time.time() - start_time
    docs_df, label_reconciliation = _augment_doc_type_metadata(docs_df, pdfs, config)
    text_scan_merge = _merge_text_scan(docs_df, config.paths)
    if text_scan_merge.get("merged"):
        docs_df = text_scan_merge["docs_df"]
    meta = {
        "probe_run_seconds": runtime,
        "error_count": len(all_errors),
        "errors": all_errors,
        "errors_sample": all_errors[:20],
        "ignored_non_pdf_files": ignored_counts,
        "ignored_non_pdf_mime_types": ignored_mime_counts,
        "ignored_non_pdf_total": int(sum(ignored_counts.values())),
        "label_reconciliation": label_reconciliation,
        "text_scan_merge": {k: v for k, v in text_scan_merge.items() if k != "docs_df"},
    }
    return pages_df, docs_df, meta


def run_probe_and_save(config: ProbeRunConfig) -> Path:
    ensure_dir(config.paths.outputs_root)
    pages_df, docs_df, meta = run_probe(config)
    return write_probe_outputs(pages_df, docs_df, config, meta)


def _augment_doc_type_metadata(
    docs_df: pd.DataFrame, pdfs_df: pd.DataFrame, config: ProbeRunConfig
) -> tuple[pd.DataFrame, Dict[str, int]]:
    docs_df = docs_df.copy()
    pdfs_df = pdfs_df.copy()
    if "rel_path" in pdfs_df.columns:
        pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)
    if "rel_path" in docs_df.columns:
        docs_df["rel_path"] = docs_df["rel_path"].astype(str).map(normalize_rel_path)

    labels_csv = labels_path(config.paths.outputs_root)
    labels_df = load_labels(labels_csv, pdfs_df)
    match_result = match_labels_to_inventory(pdfs_df, labels_df)
    label_map = (
        match_result.matched.set_index("rel_path")["label_norm"].astype(str).to_dict()
        if not match_result.matched.empty
        else {}
    )
    label_reconciliation = {
        "labels_matched": int(len(match_result.matched)),
        "labels_orphaned": int(len(match_result.orphaned)),
        "docs_unlabeled": int(len(match_result.unmatched_inventory)),
    }

    docs_df["doc_type_truth"] = docs_df["rel_path"].map(label_map).fillna("")
    heuristic_map = {
        "Text-based": "TEXT_PDF",
        "Scanned": "IMAGE_PDF",
        "Mixed": "MIXED_PDF",
    }
    classification_series = (
        docs_df["classification"] if "classification" in docs_df.columns else pd.Series([""] * len(docs_df), index=docs_df.index)
    )
    docs_df["doc_type_heuristic"] = classification_series.map(heuristic_map).fillna("")

    model_artifacts = None
    if config.use_doc_type_model and config.doc_type_model_ref:
        model_artifacts = load_doc_type_model(config.doc_type_model_ref, config.paths.outputs_root)
    if model_artifacts:
        feature_config = model_artifacts.model_card.get("feature_config", {})
        predictions = predict_doc_types(
            pdfs_df=pdfs_df,
            probe_docs=docs_df,
            model_artifacts=model_artifacts,
            pages_sampled=int(feature_config.get("pages_sampled", DEFAULT_PAGES_SAMPLED)),
            dpi=int(feature_config.get("dpi", DEFAULT_DPI)),
            seed=int(feature_config.get("seed", DEFAULT_SEED)),
            reason_features=True,
        )
        pred_map = predictions.set_index("rel_path")["predicted_label"].astype(str).to_dict()
        conf_map = predictions.set_index("rel_path")["confidence"].astype(float).to_dict()
        reason_map = predictions.set_index("rel_path")["reason_features"].astype(str).to_dict()
        docs_df["doc_type_model_pred"] = docs_df["rel_path"].map(pred_map).fillna("")
        docs_df["model_confidence"] = docs_df["rel_path"].map(conf_map)
        docs_df["reason_features"] = docs_df["rel_path"].map(reason_map).fillna("")
    else:
        docs_df["doc_type_model_pred"] = ""
        docs_df["model_confidence"] = pd.NA
        docs_df["reason_features"] = ""

    docs_df = apply_doc_type_decision(docs_df, min_confidence=config.min_model_confidence)
    return docs_df, label_reconciliation


def _merge_text_scan(docs_df: pd.DataFrame, paths: ProbePaths) -> Dict[str, object]:
    text_scan_df, _summary, run_log = load_latest_text_scan(str(paths.outputs_root))
    if text_scan_df.empty:
        return {"merged": False, "reason": "no_text_scan"}
    if run_log.get("inventory_path"):
        try:
            scan_inventory = Path(str(run_log.get("inventory_path"))).resolve()
            probe_inventory = paths.inventory.resolve()
        except Exception:
            scan_inventory = Path(str(run_log.get("inventory_path")))
            probe_inventory = paths.inventory
        if scan_inventory != probe_inventory:
            return {
                "merged": False,
                "reason": "inventory_mismatch",
                "inventory_path": str(paths.inventory),
                "text_scan_inventory_path": run_log.get("inventory_path"),
            }
    merged_df, merge_info = merge_text_scan_signals(docs_df, text_scan_df)
    if merge_info.get("merged"):
        merge_info["docs_df"] = merged_df
    return merge_info


__all__ = ["run_probe", "run_probe_and_save"]
