from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from ..config import ProbeRunConfig, new_run_id
from ..classification.doc_type.model import DOC_TYPE_LABELS
from ..utils.git import current_git_commit
from ..utils.io import ensure_dir, read_json, update_run_index, write_json, write_pointer

PROBE_POINTER = "LATEST.json"


def _has_pyarrow() -> bool:
    try:  # pragma: no cover
        import pyarrow  # noqa: F401

        return True
    except Exception:  # pragma: no cover
        return False


def _write_table(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        df.to_csv(path.with_suffix(".csv"), index=False)
        return
    if _has_pyarrow():
        df.to_parquet(path.with_suffix(".parquet"), index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _summarize(docs_df: pd.DataFrame, pages_df: pd.DataFrame, config: ProbeRunConfig, meta: Dict) -> Dict:
    total_pdfs = int(len(docs_df))
    total_pages = int(len(pages_df))
    if total_pages == 0 and "page_count" in docs_df.columns:
        total_pages = int(pd.to_numeric(docs_df["page_count"], errors="coerce").fillna(0).sum())

    classification_counts = (
        docs_df["classification"].value_counts(dropna=False).to_dict()
        if "classification" in docs_df.columns
        else {}
    )
    classification_pct = (
        {label: (count / total_pdfs) if total_pdfs else 0 for label, count in classification_counts.items()}
        if classification_counts
        else {}
    )

    pages_with_text = 0
    if "has_text" in pages_df.columns:
        pages_with_text = int(pages_df[pages_df["has_text"] == True].shape[0])  # noqa: E712
    elif "pages_with_text" in docs_df.columns:
        pages_with_text = int(pd.to_numeric(docs_df["pages_with_text"], errors="coerce").fillna(0).sum())

    baseline_ocr_pages = max(total_pages - pages_with_text, 0)
    ignored_counts = meta.get("ignored_non_pdf_files", {}) if meta else {}
    ignored_mime_counts = meta.get("ignored_non_pdf_mime_types", {}) if meta else {}

    summary = {
        "total_pdfs": total_pdfs,
        "total_pages": total_pages,
        "classification_counts": classification_counts,
        "classification_pct": classification_pct,
        "ignored_non_pdf_files": ignored_counts,
        "ignored_non_pdf_mime_types": ignored_mime_counts,
        "ignored_non_pdf_total": int(sum(ignored_counts.values())) if ignored_counts else 0,
        "pages_with_text": pages_with_text,
        "pages_without_text": baseline_ocr_pages,
        "estimated_ocr_pages_baseline": baseline_ocr_pages,
        "estimated_ocr_pages_baseline_pct": (baseline_ocr_pages / total_pages) if total_pages else 0,
    }
    if "text_coverage_pct" in docs_df:
        top_scanned = docs_df.sort_values("text_coverage_pct").head(20)
        summary["top_scanned_docs"] = top_scanned[["doc_id", "rel_path", "text_coverage_pct"]].fillna(0).to_dict(orient="records")
    summary["thresholds"] = {
        "text_char_threshold": config.text_char_threshold,
        "doc_text_pct_text": config.doc_text_pct_text,
        "doc_text_pct_scanned": config.doc_text_pct_scanned,
    }
    if meta and meta.get("text_scan_merge"):
        summary["text_scan_merge"] = meta.get("text_scan_merge")
        if not meta["text_scan_merge"].get("merged"):
            reason = meta["text_scan_merge"].get("reason", "")
            if reason and reason not in {"no_text_scan", "missing_data"}:
                summary.setdefault("warnings", []).append(
                    "Latest text_scan run did not match this probe run; text_scan signals were not merged."
                )
    doc_type_eval = _evaluate_doc_types(docs_df)
    if doc_type_eval:
        summary["doc_type_evaluation"] = doc_type_eval
    return summary


def _infer_inventory_label(inventory_path: Path) -> str | None:
    summary_path = inventory_path.with_name("inventory_summary.json")
    summary = read_json(summary_path)
    source_root_name = summary.get("source_root_name")
    if source_root_name:
        return str(source_root_name)
    return None


def build_probe_run_id(inventory_path: Path) -> str:
    return new_run_id("probe", label=_infer_inventory_label(inventory_path))


def _infer_source_root(inventory_path: Path) -> tuple[Path, str]:
    run_log = read_json(inventory_path.with_name("run_log.json"))
    root_value = run_log.get("root")
    root_name = run_log.get("source_root_name")
    if root_value:
        source_root = Path(root_value)
    else:
        source_root = inventory_path
    if not root_name:
        summary = read_json(inventory_path.with_name("inventory_summary.json"))
        root_name = summary.get("source_root_name") or source_root.name
    return source_root, root_name


def write_probe_outputs(
    pages_df: pd.DataFrame,
    docs_df: pd.DataFrame,
    config: ProbeRunConfig,
    meta: Dict,
    *,
    probe_run_id: str | None = None,
) -> Path:
    probe_root = ensure_dir(Path(config.paths.outputs_root) / "probes")
    probe_run_id = probe_run_id or build_probe_run_id(config.paths.inventory)
    run_dir = probe_root / probe_run_id
    ensure_dir(run_dir)

    pages_df = pages_df.copy()
    docs_df = docs_df.copy()
    pages_df.insert(0, "probe_run_id", probe_run_id)
    docs_df.insert(0, "probe_run_id", probe_run_id)

    _write_table(pages_df, run_dir / "readiness_pages")
    _write_table(docs_df, run_dir / "readiness_docs")

    summary = _summarize(docs_df, pages_df, config, meta)
    summary_path = write_json(run_dir / "probe_summary.json", summary)

    label_reconciliation = meta.get("label_reconciliation") if meta else None
    if label_reconciliation:
        write_json(run_dir / "label_reconciliation.json", label_reconciliation)

    run_log = {
        "probe_run_id": probe_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_path": str(config.paths.inventory),
        "output_root": str(config.paths.outputs_root),
        "config": config.run_args,
        "meta": meta,
        "git_commit": current_git_commit(),
    }
    log_path = write_json(run_dir / "probe_run_log.json", run_log)

    pointer_payload = {
        "probe_run_id": probe_run_id,
        "run_dir": str(Path("probes") / probe_run_id),
        "inventory": str(config.paths.inventory),
        "summary": str(Path("probes") / probe_run_id / "probe_summary.json"),
    }
    write_pointer(probe_root, PROBE_POINTER, pointer_payload)
    source_root, source_root_name = _infer_source_root(config.paths.inventory)
    inventory_run_log = read_json(config.paths.inventory.with_name("run_log.json"))
    inventory_run_id = inventory_run_log.get("inventory_run_id") or config.paths.inventory.parent.name
    update_run_index(
        Path(config.paths.outputs_root),
        source_root=source_root,
        source_root_name=source_root_name,
        probe={
            "run_id": probe_run_id,
            "run_dir": str(Path("probes") / probe_run_id),
            "summary": str(Path("probes") / probe_run_id / "probe_summary.json"),
            "run_log": str(Path("probes") / probe_run_id / "probe_run_log.json"),
            "inventory": str(config.paths.inventory),
            "inventory_run_id": inventory_run_id,
            "timestamp": run_log["timestamp"],
        },
    )

    return run_dir


def _evaluate_doc_types(docs_df: pd.DataFrame) -> Dict[str, object]:
    if "doc_type_truth" not in docs_df.columns:
        return {}
    labeled = docs_df.copy()
    labeled = labeled[labeled["doc_type_truth"].fillna("").astype(str).str.strip() != ""]
    if labeled.empty:
        return {}

    eval_payload: Dict[str, object] = {"labeled_docs": int(len(labeled))}
    eval_payload["heuristic"] = _build_confusion_metrics(labeled, "doc_type_heuristic")

    has_model_preds = (
        "doc_type_model_pred" in labeled.columns
        and labeled["doc_type_model_pred"].fillna("").astype(str).str.strip().any()
    )
    if has_model_preds:
        eval_payload["model"] = _build_confusion_metrics(labeled, "doc_type_model_pred")

    eval_payload["top_mismatches"] = {
        "heuristic": _collect_mismatches(labeled, "doc_type_heuristic"),
    }
    if has_model_preds:
        eval_payload["top_mismatches"]["model"] = _collect_mismatches(
            labeled, "doc_type_model_pred", confidence_col="model_confidence"
        )
    return eval_payload


def _build_confusion_metrics(df: pd.DataFrame, pred_col: str) -> Dict[str, object]:
    truth = df["doc_type_truth"].astype(str)
    preds = df[pred_col].fillna("").astype(str)
    labels = [label for label in DOC_TYPE_LABELS if label in set(truth) or label in set(preds)]
    matrix = pd.crosstab(truth, preds, rownames=["truth"], colnames=["pred"]).reindex(index=labels, columns=labels, fill_value=0)
    total = int(matrix.to_numpy().sum())
    correct = int(sum(matrix.loc[label, label] for label in labels if label in matrix.index))
    per_class = {}
    for label in labels:
        denom = int(matrix.loc[label].sum()) if label in matrix.index else 0
        per_class[label] = (matrix.loc[label, label] / denom) if denom else 0
    return {
        "labels": labels,
        "confusion_matrix": matrix.values.tolist(),
        "accuracy": (correct / total) if total else 0,
        "accuracy_per_class": per_class,
    }


def _collect_mismatches(
    df: pd.DataFrame,
    pred_col: str,
    *,
    confidence_col: str = "",
    limit: int = 50,
) -> List[Dict[str, object]]:
    mismatches = df[df[pred_col].astype(str) != df["doc_type_truth"].astype(str)].copy()
    if confidence_col and confidence_col in mismatches.columns:
        mismatches = mismatches.sort_values(confidence_col)
    records = []
    for _, row in mismatches.head(limit).iterrows():
        records.append(
            {
                "rel_path": row.get("rel_path"),
                "truth": row.get("doc_type_truth"),
                "predicted": row.get(pred_col),
                "confidence": row.get(confidence_col) if confidence_col else None,
                "reason_features": row.get("reason_features", ""),
            }
        )
    return records


__all__ = ["build_probe_run_id", "write_probe_outputs"]
