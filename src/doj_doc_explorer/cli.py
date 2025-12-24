from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DEFAULT_OUTPUT_ROOT, InventoryConfig, ProbePaths, ProbeRunConfig
from .inventory.runner import InventoryRunner
from .probe.runner import run_probe_and_save
from .text_scan.config import TextQualityConfig, TextScanRunConfig
from .text_scan.runner import run_text_scan_and_save
from .utils.io import ensure_dir, latest_inventory, latest_probe, load_table, read_json, self_check, write_json
from .utils.paths import normalize_rel_path
from .classification.doc_type.features import DEFAULT_DPI, DEFAULT_PAGES_SAMPLED, DEFAULT_SEED
from .classification.doc_type.model import (
    load_doc_type_model,
    predict_doc_types,
    resolve_doc_type_model_path,
    train_doc_type_model,
)
from .pdf_type.labels import (
    LABEL_VALUES,
    filter_pdf_inventory,
    inventory_identity,
    labels_path,
    load_inventory,
    load_labels,
    match_labels_to_inventory,
    normalize_label_value,
    normalize_labels_for_save,
    reconcile_labels,
    write_labels,
)

from src.probe_readiness import list_pdfs, stable_doc_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DOJ doc explorer toolkit")
    subparsers = parser.add_subparsers(dest="command")

    inv = subparsers.add_parser("inventory", help="Inventory commands")
    inv_sub = inv.add_subparsers(dest="subcommand")
    inv_run = inv_sub.add_parser("run", help="Run inventory scan")
    inv_run.add_argument("--root", required=True, help="Dataset root folder")
    inv_run.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    inv_run.add_argument("--hash", default="sha256", choices=["none", "md5", "sha1", "sha256"], help="Hash algorithm")
    inv_run.add_argument("--sample-bytes", dest="sample_bytes", type=int, default=0, help="Bytes for sample hash")
    inv_run.add_argument("--ignore", action="append", default=[], help="Glob patterns to ignore")
    inv_run.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks")
    inv_run.add_argument("--max-files", type=int, default=None, help="Optional safety limit")
    inv_run.set_defaults(func=run_inventory_cmd)

    probe = subparsers.add_parser("probe", help="Probe commands")
    probe_sub = probe.add_subparsers(dest="subcommand")
    probe_run = probe_sub.add_parser("run", help="Run probe against an inventory")
    probe_run.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    probe_run.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    probe_run.add_argument("--text-threshold", type=int, default=25, help="Characters required to mark text")
    probe_run.add_argument(
        "--doc-text-pct-text",
        type=float,
        default=0.50,
        help="Pct of pages with extractable text to call doc text-based",
    )
    probe_run.add_argument(
        "--doc-text-min-chars-per-page",
        type=int,
        default=200,
        help="Minimum average extractable characters per page to call doc text-based",
    )
    probe_run.add_argument("--doc-text-pct-scanned", type=float, default=0.10, help="Pct of pages with text to call doc scanned")
    probe_run.add_argument("--max-pdfs", type=int, default=0, help="Limit number of PDFs (0 = all)")
    probe_run.add_argument("--max-pages", type=int, default=0, help="Limit pages per PDF (0 = all)")
    probe_run.add_argument("--skip-text-check", action="store_true", help="Skip text readiness check")
    probe_run.add_argument("--seed", type=int, default=None, help="Random seed")
    probe_run.add_argument("--only-top-folder", default=None, help="Filter by top-level folder")
    probe_run.add_argument(
        "--use-doc-type-model",
        dest="use_doc_type_model",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use the doc-type model when available",
    )
    probe_run.add_argument("--model", default="LATEST", help="Doc-type model reference (LATEST, path, or model id)")
    probe_run.add_argument(
        "--min-model-confidence",
        type=float,
        default=0.70,
        help="Minimum confidence to trust doc-type model predictions",
    )
    probe_run.set_defaults(func=run_probe_cmd)

    text_scan = subparsers.add_parser("text_scan", help="Text scan commands")
    text_scan_sub = text_scan.add_subparsers(dest="subcommand")
    text_scan_run = text_scan_sub.add_parser("run", help="Run text scan against probe outputs")
    text_scan_run.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    text_scan_run.add_argument("--probe", default="LATEST", help="Probe run id, path, or LATEST")
    text_scan_run.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    text_scan_run.add_argument("--max-docs", type=int, default=0, help="Limit number of PDFs (0 = all)")
    text_scan_run.add_argument("--max-pages", type=int, default=0, help="Limit pages per PDF (0 = all)")
    text_scan_run.add_argument(
        "--min-text-pages",
        type=int,
        default=1,
        help="Minimum pages marked as text in probe before scanning",
    )
    text_scan_run.add_argument(
        "--store-snippet",
        dest="store_snippet",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Store a short sanitized text snippet for debugging",
    )
    text_scan_run.add_argument("--seed", type=int, default=42, help="Sampling seed")
    text_scan_run.add_argument("--empty-min-chars", type=int, default=50, help="Chars threshold for EMPTY")
    text_scan_run.add_argument("--empty-min-words", type=int, default=10, help="Words threshold for EMPTY")
    text_scan_run.add_argument("--min-alpha-ratio", type=float, default=0.45, help="Minimum alpha ratio for GOOD")
    text_scan_run.add_argument("--min-printable-ratio", type=float, default=0.95, help="Minimum printable ratio for GOOD")
    text_scan_run.add_argument("--max-gibberish", type=float, default=0.60, help="Max gibberish score for GOOD")
    text_scan_run.add_argument("--gibberish-min-words", type=int, default=30, help="Words threshold for gibberish")
    text_scan_run.add_argument(
        "--gibberish-symbol-ratio",
        type=float,
        default=0.45,
        help="Symbol ratio threshold for gibberish",
    )
    text_scan_run.set_defaults(func=run_text_scan_cmd)

    qa = subparsers.add_parser("qa", help="QA helpers")
    qa_sub = qa.add_subparsers(dest="subcommand")
    qa_open = qa_sub.add_parser("open", help="Print Streamlit command")
    qa_open.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    qa_open.set_defaults(func=run_qa_open)

    health = subparsers.add_parser("self-check", help="Prepare expected folders")
    health.set_defaults(func=run_self_check)

    pdf_type = subparsers.add_parser("pdf_type", help="PDF type labeling and model helpers")
    pdf_sub = pdf_type.add_subparsers(dest="subcommand")

    pdf_label = pdf_sub.add_parser("label", help="Label a PDF by relative path")
    pdf_label.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    pdf_label.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    pdf_label.add_argument("--rel-path", required=True, help="Relative path to the PDF to label")
    pdf_label.add_argument("--label", required=True, choices=sorted(LABEL_VALUES), help="Label to apply")
    pdf_label.add_argument("--source-probe-run", default="", help="Optional probe run id used for labeling")
    pdf_label.add_argument("--notes", default="", help="Optional notes for the label")
    pdf_label.add_argument("--labeling-version", default="", help="Optional labeling schema version")
    pdf_label.add_argument("--overwrite", action="store_true", help="Overwrite an existing label")
    pdf_label.set_defaults(func=run_pdf_type_label_cmd)

    pdf_train = pdf_sub.add_parser("train", help="Prepare training data from labels")
    pdf_train.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    pdf_train.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    pdf_train.add_argument("--exclude-mixed", action="store_true", help="Exclude MIXED_PDF labels from training")
    pdf_train.add_argument("--output", default="", help="Optional output CSV path for training data")
    pdf_train.set_defaults(func=run_pdf_type_train_cmd)

    pdf_predict = pdf_sub.add_parser("predict", help="Generate predictions for unlabeled PDFs")
    pdf_predict.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    pdf_predict.add_argument("--probe", default="LATEST", help="Probe run id, path, or LATEST")
    pdf_predict.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    pdf_predict.add_argument("--output", default="", help="Optional output CSV path for predictions")
    pdf_predict.set_defaults(func=run_pdf_type_predict_cmd)

    pdf_migrate = pdf_sub.add_parser("migrate", help="Normalize legacy PDF type labels safely")
    pdf_migrate.add_argument("--labels", required=True, help="Path to the labels CSV to upgrade")
    pdf_migrate.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    pdf_migrate.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    pdf_migrate.add_argument("--write", action="store_true", help="Write the upgraded labels file")
    pdf_migrate.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    pdf_migrate.set_defaults(func=run_pdf_type_migrate_cmd)

    doc_type = subparsers.add_parser("doc_type", help="Doc-type model training and inference")
    doc_type_sub = doc_type.add_subparsers(dest="subcommand")

    doc_train = doc_type_sub.add_parser("train", help="Train a doc-type classifier from labels")
    doc_train.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    doc_train.add_argument("--probe", default="LATEST", help="Probe run id, path, or LATEST")
    doc_train.add_argument("--labels", default=str(labels_path(DEFAULT_OUTPUT_ROOT)), help="Labels CSV path")
    doc_train.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    doc_train.add_argument("--pages-sampled", type=int, default=DEFAULT_PAGES_SAMPLED, help="Pages sampled per PDF")
    doc_train.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Render DPI for thumbnails")
    doc_train.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic sampling seed")
    doc_train.add_argument("--eval-split", type=float, default=0.2, help="Eval split fraction")
    doc_train.set_defaults(func=run_doc_type_train_cmd)

    doc_predict = doc_type_sub.add_parser("predict", help="Predict doc types for selected docs")
    doc_predict.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    doc_predict.add_argument("--probe", default="LATEST", help="Probe run id, path, or LATEST")
    doc_predict.add_argument("--model", default="LATEST", help="Doc-type model reference (LATEST, path, or model id)")
    doc_predict.add_argument("--selection", default="", help="Optional CSV with rel_path or doc_id to score")
    doc_predict.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    doc_predict.add_argument("--only-unlabeled", action="store_true", help="Predict only unlabeled docs")
    doc_predict.set_defaults(func=run_doc_type_predict_cmd)

    doc_queue = doc_type_sub.add_parser("queue", help="Queue low-confidence docs for labeling")
    doc_queue.add_argument("--inventory", default="LATEST", help="Inventory path or run id or LATEST")
    doc_queue.add_argument("--probe", default="LATEST", help="Probe run id, path, or LATEST")
    doc_queue.add_argument("--model", default="LATEST", help="Doc-type model reference (LATEST, path, or model id)")
    doc_queue.add_argument("--k", type=int, default=200, help="Number of docs to queue")
    doc_queue.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    doc_queue.set_defaults(func=run_doc_type_queue_cmd)

    return parser


def run_inventory_cmd(args: argparse.Namespace) -> None:
    runner = InventoryRunner()
    config = runner.create_config(
        root=Path(args.root),
        out_dir=Path(args.out),
        hash_algorithm=args.hash,
        sample_bytes=args.sample_bytes,
        ignore_patterns=args.ignore,
        follow_symlinks=args.follow_symlinks,
        max_files=args.max_files,
    )
    result = runner.run(config)
    print("Inventory complete")
    print(f"Run dir  : {result.run_dir}")
    print(f"CSV      : {result.csv_path}")
    print(f"Summary  : {result.summary_path}")
    print(f"Log      : {result.log_path}")


def resolve_inventory_path(value: str, outputs_root: Path) -> Path:
    if value == "LATEST":
        found = latest_inventory(outputs_root)
        if not found:
            raise SystemExit("No inventory found. Run an inventory first.")
        return found
    candidate = Path(value)
    if candidate.exists():
        return candidate
    run_dir = outputs_root / "inventory" / value / "inventory.csv"
    if run_dir.exists():
        return run_dir
    raise SystemExit(f"Could not locate inventory at {value}")


def run_probe_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    model_path = resolve_doc_type_model_path(args.model, outputs_root)
    use_doc_type_model = args.use_doc_type_model
    if use_doc_type_model is None:
        use_doc_type_model = model_path is not None
    if not use_doc_type_model:
        model_path = None
    config = ProbeRunConfig(
        paths=ProbePaths(inventory=inventory_path, outputs_root=outputs_root),
        text_char_threshold=args.text_threshold,
        doc_text_pct_text=args.doc_text_pct_text,
        doc_text_pct_scanned=args.doc_text_pct_scanned,
        doc_text_min_chars_per_page=args.doc_text_min_chars_per_page,
        max_pdfs=args.max_pdfs,
        max_pages=args.max_pages,
        skip_text_check=args.skip_text_check,
        seed=args.seed,
        only_top_folder=args.only_top_folder,
        use_doc_type_model=use_doc_type_model,
        doc_type_model_ref=args.model if model_path else "",
        min_model_confidence=args.min_model_confidence,
    )
    run_dir = run_probe_and_save(config)
    print("Probe run complete")
    print(f"Run dir  : {run_dir}")
    print(f"Summary  : {run_dir / 'probe_summary.json'}")


def run_text_scan_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    probe_run_dir = resolve_probe_run_dir(args.probe, outputs_root)
    quality_config = TextQualityConfig(
        empty_min_chars=args.empty_min_chars,
        empty_min_words=args.empty_min_words,
        min_alpha_ratio=args.min_alpha_ratio,
        min_printable_ratio=args.min_printable_ratio,
        max_gibberish=args.max_gibberish,
        gibberish_min_words=args.gibberish_min_words,
        gibberish_symbol_ratio=args.gibberish_symbol_ratio,
    )
    config = TextScanRunConfig(
        inventory_path=inventory_path,
        probe_run_dir=probe_run_dir,
        outputs_root=outputs_root,
        max_docs=args.max_docs,
        max_pages=args.max_pages,
        min_text_pages=args.min_text_pages,
        seed=args.seed,
        store_snippet=args.store_snippet,
        quality=quality_config,
    )
    run_dir = run_text_scan_and_save(config)
    print("Text scan complete")
    print(f"Run dir  : {run_dir}")
    print(f"Summary  : {run_dir / 'text_scan_summary.json'}")


def run_pdf_type_label_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    inventory_df = filter_pdf_inventory(load_inventory(inventory_path))
    labels_csv = labels_path(outputs_root)
    labels_df = load_labels(labels_csv, inventory_df)
    inventory_id = inventory_identity(inventory_path)

    rel_path = normalize_rel_path(args.rel_path)
    label_value = str(args.label).upper()
    if label_value not in LABEL_VALUES:
        raise SystemExit(f"Label must be one of {sorted(LABEL_VALUES)}")

    existing = labels_df[labels_df["rel_path"] == rel_path]
    if not existing.empty:
        existing_label = existing.iloc[0].get("label_norm", "")
        print(f"Existing label for {rel_path}: {existing_label}")
        if not args.overwrite:
            if sys.stdin.isatty():
                confirm = input("Overwrite existing label? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    match_result = match_labels_to_inventory(inventory_df, labels_df)
                    reconcile_labels(
                        inventory_df=inventory_df,
                        labels_df=labels_df,
                        outputs_root=outputs_root,
                        inventory_id=inventory_id,
                        match_result=match_result,
                    )
                    print("Label unchanged.")
                    return
            else:
                raise SystemExit("Label already exists. Use --overwrite to replace.")

    doc_id_at_label_time = ""
    sha_at_label_time = ""
    inventory_matches = inventory_df[inventory_df["rel_path"] == rel_path]
    if not inventory_matches.empty:
        row = inventory_matches.iloc[0]
        doc_id_at_label_time = _compute_doc_id_from_row(row)
        hash_value = row.get("hash_value")
        if isinstance(hash_value, str) and len(hash_value) == 64:
            sha_at_label_time = hash_value
    else:
        print(f"Warning: rel_path {rel_path} not found in current inventory.")

    label_record = {
        "rel_path": rel_path,
        "label_raw": label_value,
        "label_norm": normalize_label_value(label_value),
        "labeled_at": datetime.now(timezone.utc).isoformat(),
        "source_inventory_run": inventory_id,
        "source_probe_run": args.source_probe_run or "",
        "doc_id_at_label_time": doc_id_at_label_time,
        "sha256_at_label_time": sha_at_label_time,
        "notes": args.notes or "",
        "labeling_version": args.labeling_version or "",
    }

    labels_df = labels_df[labels_df["rel_path"] != rel_path]
    labels_df = pd.concat([labels_df, pd.DataFrame([label_record])], ignore_index=True)
    labels_df = normalize_labels_for_save(labels_df)
    write_labels(labels_df, labels_csv)
    print(f"Labeled rel_path: {rel_path}")
    if doc_id_at_label_time:
        print(f"doc_id (current run): {doc_id_at_label_time}")
    print(f"Saved labels to {labels_csv}")

    match_result = match_labels_to_inventory(inventory_df, labels_df)
    reconcile_labels(
        inventory_df=inventory_df,
        labels_df=labels_df,
        outputs_root=outputs_root,
        inventory_id=inventory_id,
        match_result=match_result,
    )


def run_pdf_type_train_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    inventory_df = filter_pdf_inventory(load_inventory(inventory_path))
    labels_csv = labels_path(outputs_root)
    labels_df = load_labels(labels_csv, inventory_df)
    inventory_id = inventory_identity(inventory_path)

    match_result = match_labels_to_inventory(inventory_df, labels_df)
    reconcile_labels(
        inventory_df=inventory_df,
        labels_df=labels_df,
        outputs_root=outputs_root,
        inventory_id=inventory_id,
        match_result=match_result,
    )

    matched_df = match_result.matched.copy()
    if matched_df.empty:
        print("No matched labels found. Training dataset was not generated.")
        return
    if args.exclude_mixed:
        matched_df = matched_df[matched_df["label_norm"] != "MIXED_PDF"]

    matched_df["doc_id"] = matched_df.apply(_compute_doc_id_from_row, axis=1)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (labels_csv.parent / f"pdf_type_training_{timestamp}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_columns = [
        "rel_path",
        "label_norm",
        "label_raw",
        "doc_id",
        "top_level_folder",
        "size_bytes",
        "modified_time",
        "hash_value",
        "labeled_at",
        "source_inventory_run",
        "source_probe_run",
        "notes",
        "labeling_version",
    ]
    output_df = matched_df[[col for col in output_columns if col in matched_df.columns]]
    output_df.to_csv(output_path, index=False)
    print(f"Wrote training dataset with {len(output_df)} labels to {output_path}")


def run_pdf_type_predict_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    inventory_df = filter_pdf_inventory(load_inventory(inventory_path))
    labels_csv = labels_path(outputs_root)
    labels_df = load_labels(labels_csv, inventory_df)
    inventory_id = inventory_identity(inventory_path)

    match_result = match_labels_to_inventory(inventory_df, labels_df)
    reconcile_labels(
        inventory_df=inventory_df,
        labels_df=labels_df,
        outputs_root=outputs_root,
        inventory_id=inventory_id,
        match_result=match_result,
    )

    unlabeled_df = match_result.unmatched_inventory.copy()
    if unlabeled_df.empty:
        print("All PDFs are already labeled. No predictions generated.")
        return

    probe_docs, probe_run_id = _load_probe_docs(args.probe, outputs_root)
    label_map = {}
    if not probe_docs.empty:
        probe_docs = probe_docs.copy()
        probe_docs["rel_path"] = probe_docs["rel_path"].astype(str).map(normalize_rel_path)
        classification_map = {
            "Text-based": "TEXT_PDF",
            "Scanned": "IMAGE_PDF",
            "Mixed": "MIXED_PDF",
        }
        probe_docs["predicted_label"] = probe_docs["classification"].map(classification_map).fillna("")
        label_map = (
            probe_docs.set_index("rel_path")["predicted_label"].astype(str).to_dict()
            if "rel_path" in probe_docs.columns
            else {}
        )
    elif args.probe:
        print("Warning: Probe data not found; predictions will be blank.")

    unlabeled_df["doc_id"] = unlabeled_df.apply(_compute_doc_id_from_row, axis=1)
    unlabeled_df["predicted_label"] = unlabeled_df["rel_path"].map(label_map).fillna("")
    unlabeled_df["prediction_source"] = unlabeled_df["predicted_label"].apply(
        lambda value: "probe_classification" if value else "missing_probe_classification"
    )
    unlabeled_df["predicted_at"] = datetime.now(timezone.utc).isoformat()
    unlabeled_df["source_probe_run"] = probe_run_id

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (labels_csv.parent / f"pdf_type_predictions_{timestamp}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_columns = [
        "rel_path",
        "doc_id",
        "predicted_label",
        "prediction_source",
        "predicted_at",
        "source_probe_run",
        "top_level_folder",
    ]
    output_df = unlabeled_df[[col for col in output_columns if col in unlabeled_df.columns]]
    output_df.to_csv(output_path, index=False)
    print(f"Wrote predictions for {len(output_df)} unlabeled PDFs to {output_path}")


def run_doc_type_train_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    labels_csv = Path(args.labels)
    artifacts, eval_payload = train_doc_type_model(
        inventory_path=inventory_path,
        probe_ref=args.probe,
        labels_csv=labels_csv,
        outputs_root=outputs_root,
        pages_sampled=args.pages_sampled,
        dpi=args.dpi,
        seed=args.seed,
        eval_split=args.eval_split,
    )
    print("Doc-type model training complete")
    print(f"Model dir: {artifacts.model_dir}")
    label_reconciliation = artifacts.model_card.get("label_reconciliation", {})
    if label_reconciliation:
        print(
            "Label reconciliation:",
            f"matched={label_reconciliation.get('labels_matched')}",
            f"orphaned={label_reconciliation.get('labels_orphaned')}",
            f"unlabeled={label_reconciliation.get('docs_unlabeled')}",
        )
    if eval_payload.get("confusion_matrix") is not None:
        print("Confusion matrix (eval split):")
        print(pd.DataFrame(eval_payload.get("confusion_matrix", []), index=eval_payload.get("labels", [])))
    if eval_payload.get("classification_report"):
        print("Per-class precision/recall (eval split):")
        report = pd.DataFrame(eval_payload["classification_report"]).transpose()
        print(report[["precision", "recall", "f1-score", "support"]])


def run_doc_type_predict_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    pdfs_df, _, _ = list_pdfs(inventory_path, extract_root=outputs_root)
    pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)

    model_artifacts = load_doc_type_model(args.model, outputs_root)
    if not model_artifacts:
        raise SystemExit("Doc-type model not found. Train a model first.")

    labels_df = load_labels(labels_path(outputs_root), pdfs_df)
    match_result = match_labels_to_inventory(pdfs_df, labels_df)
    labeled_paths = set(match_result.matched["rel_path"].astype(str)) if not match_result.matched.empty else set()

    selection_df = _load_selection_csv(args.selection)
    if selection_df is not None:
        pdfs_df = _apply_selection(pdfs_df, selection_df)

    if args.only_unlabeled:
        pdfs_df = pdfs_df[~pdfs_df["rel_path"].isin(labeled_paths)].copy()

    if pdfs_df.empty:
        print("No PDFs matched the selection criteria.")
        return

    probe_docs, _ = _load_probe_docs(args.probe, outputs_root)
    feature_config = model_artifacts.model_card.get("feature_config", {})
    predictions = predict_doc_types(
        pdfs_df=pdfs_df,
        probe_docs=probe_docs,
        model_artifacts=model_artifacts,
        pages_sampled=int(feature_config.get("pages_sampled", DEFAULT_PAGES_SAMPLED)),
        dpi=int(feature_config.get("dpi", DEFAULT_DPI)),
        seed=int(feature_config.get("seed", DEFAULT_SEED)),
        reason_features=True,
    )

    run_id = new_run_id("doc_type_predict", label=_infer_inventory_label(inventory_path))
    run_dir = ensure_dir(outputs_root / "classification" / "doc_type" / run_id)
    output_path = run_dir / "doc_type_predictions.csv"
    predictions.to_csv(output_path, index=False)
    print(f"Wrote predictions for {len(predictions)} PDFs to {output_path}")


def run_doc_type_queue_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    pdfs_df, _, _ = list_pdfs(inventory_path, extract_root=outputs_root)
    pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)

    model_artifacts = load_doc_type_model(args.model, outputs_root)
    if not model_artifacts:
        raise SystemExit("Doc-type model not found. Train a model first.")

    labels_df = load_labels(labels_path(outputs_root), pdfs_df)
    match_result = match_labels_to_inventory(pdfs_df, labels_df)
    unlabeled_df = match_result.unmatched_inventory.copy()
    if unlabeled_df.empty:
        print("All PDFs already labeled. No queue generated.")
        return

    probe_docs, _ = _load_probe_docs(args.probe, outputs_root)
    feature_config = model_artifacts.model_card.get("feature_config", {})
    predictions = predict_doc_types(
        pdfs_df=unlabeled_df,
        probe_docs=probe_docs,
        model_artifacts=model_artifacts,
        pages_sampled=int(feature_config.get("pages_sampled", DEFAULT_PAGES_SAMPLED)),
        dpi=int(feature_config.get("dpi", DEFAULT_DPI)),
        seed=int(feature_config.get("seed", DEFAULT_SEED)),
        reason_features=False,
    )
    if predictions.empty:
        print("No predictions available for queue.")
        return

    queue_df = _select_low_confidence(predictions, args.k)
    queue_df = queue_df[["rel_path", "predicted_label", "confidence"]].rename(
        columns={"predicted_label": "suggested_label"}
    )
    queue_path = ensure_dir(outputs_root / "labels") / "label_queue.csv"
    queue_df.to_csv(queue_path, index=False)
    print(f"Wrote label queue with {len(queue_df)} docs to {queue_path}")


def run_pdf_type_migrate_cmd(args: argparse.Namespace) -> None:
    outputs_root = Path(args.out)
    inventory_path = resolve_inventory_path(args.inventory, outputs_root)
    inventory_df = filter_pdf_inventory(load_inventory(inventory_path))
    labels_csv = Path(args.labels)
    labels_df = load_labels(labels_csv, inventory_df, write_back=False)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    normalized_raw = labels_df["label_raw"].fillna("").astype(str).str.strip().str.upper()
    normalized_labels = labels_df["label_raw"].map(normalize_label_value)

    labels_with_raw_text = int((normalized_raw == "TEXT_PDF").sum())
    labels_to_change = int((normalized_raw == "TEXT_PDF").sum())
    labels_already_normalized = int(
        (
            normalized_raw.isin({"IMAGE_PDF", "MIXED_PDF", "IMAGE_OF_TEXT_PDF"})
            & (normalized_labels == normalized_raw)
        ).sum()
    )
    labels_unknown = int(pd.isna(normalized_labels).sum())
    sample_changes = labels_df.loc[normalized_raw == "TEXT_PDF", "rel_path"].head(25).tolist()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_reference": {
            "run_id": inventory_identity(inventory_path),
            "path": str(inventory_path),
        },
        "total_labels": int(len(labels_df)),
        "labels_with_raw_TEXT_PDF": labels_with_raw_text,
        "labels_to_change_TEXT_to_IMAGE_OF_TEXT": labels_to_change,
        "labels_already_normalized": labels_already_normalized,
        "labels_unknown": labels_unknown,
        "sample_rel_paths_to_change": sample_changes,
    }
    report_path = labels_path(outputs_root).parent / f"migration_report_{timestamp}.json"
    write_json(report_path, report)
    print(f"Wrote migration report to {report_path}")

    do_write = args.write and not args.dry_run
    if not do_write:
        print("Dry-run complete. Labels file was not modified.")
        return

    if labels_csv.exists():
        backup_dir = labels_path(outputs_root).parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"pdf_type_labels_{timestamp}.csv"
        shutil.copy2(labels_csv, backup_path)
        print(f"Backup created at {backup_path}")

    labels_df = normalize_labels_for_save(labels_df)
    write_labels(labels_df, labels_csv)
    print(f"Wrote upgraded labels to {labels_csv}")


def run_qa_open(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    cmd = f"streamlit run app/Home.py -- --out {out_dir}"
    print("Launch QA UI with:")
    print(cmd)


def run_self_check(args: argparse.Namespace) -> None:
    info = self_check(DEFAULT_OUTPUT_ROOT)
    print("Prepared folders:")
    for key, value in info.items():
        print(f"- {key}: {value}")


def _infer_inventory_label(inventory_path: Path) -> str | None:
    summary = read_json(inventory_path.with_name("inventory_summary.json"))
    return summary.get("source_root_name") if summary else None


def _load_selection_csv(path_value: str) -> pd.DataFrame | None:
    if not path_value:
        return None
    selection_path = Path(path_value)
    if not selection_path.exists():
        raise SystemExit(f"Selection CSV not found: {selection_path}")
    selection_df = pd.read_csv(selection_path)
    if "rel_path" in selection_df.columns:
        selection_df["rel_path"] = selection_df["rel_path"].astype(str).map(normalize_rel_path)
    return selection_df


def _apply_selection(pdfs_df: pd.DataFrame, selection_df: pd.DataFrame) -> pd.DataFrame:
    if "rel_path" in selection_df.columns:
        selection_paths = set(selection_df["rel_path"].dropna().astype(str))
        return pdfs_df[pdfs_df["rel_path"].isin(selection_paths)].copy()
    if "doc_id" in selection_df.columns:
        selection_ids = set(selection_df["doc_id"].dropna().astype(str))
        return pdfs_df[pdfs_df["doc_id"].astype(str).isin(selection_ids)].copy()
    raise SystemExit("Selection CSV must include rel_path or doc_id column.")


def _select_low_confidence(predictions: pd.DataFrame, k: int) -> pd.DataFrame:
    if predictions.empty or k <= 0:
        return predictions.head(0)
    if "top_level_folder" not in predictions.columns:
        return predictions.sort_values("confidence").head(k)
    grouped = {
        folder: group.sort_values("confidence").reset_index(drop=True)
        for folder, group in predictions.groupby("top_level_folder", dropna=False)
    }
    selected_rows = []
    while grouped and len(selected_rows) < k:
        for folder in list(grouped.keys()):
            group = grouped[folder]
            if group.empty:
                grouped.pop(folder, None)
                continue
            selected_rows.append(group.iloc[0])
            grouped[folder] = group.iloc[1:].reset_index(drop=True)
            if len(selected_rows) >= k:
                break
    return pd.DataFrame(selected_rows)


def _compute_doc_id_from_row(row: pd.Series) -> str:
    series = pd.Series(
        {
            "sha256": row.get("sha256"),
            "rel_path": row.get("rel_path"),
            "size_bytes": row.get("size_bytes"),
            "modified_time": row.get("modified_time"),
        }
    )
    return stable_doc_id(series)


def _load_probe_docs(value: str, outputs_root: Path) -> tuple[pd.DataFrame, str]:
    if not value or value.upper() == "NONE":
        return pd.DataFrame(), ""
    if value == "LATEST":
        latest = latest_probe(outputs_root)
        if latest:
            run_dir, pointer = latest
            docs = load_table(run_dir / "readiness_docs")
            return docs, pointer.get("probe_run_id", run_dir.name)
        return pd.DataFrame(), ""
    candidate = Path(value)
    if candidate.exists():
        if candidate.is_dir():
            docs = load_table(candidate / "readiness_docs")
            return docs, candidate.name
        return load_table(candidate), candidate.stem
    run_dir = outputs_root / "probes" / value
    if run_dir.exists():
        docs = load_table(run_dir / "readiness_docs")
        return docs, run_dir.name
    return pd.DataFrame(), ""


def resolve_probe_run_dir(value: str, outputs_root: Path) -> Path:
    if value == "LATEST":
        latest = latest_probe(outputs_root)
        if latest:
            run_dir, _pointer = latest
            return run_dir
        raise SystemExit("No probe run found. Run a probe first.")
    candidate = Path(value)
    if candidate.exists():
        if candidate.is_dir():
            return candidate
        return candidate.parent
    run_dir = outputs_root / "probes" / value
    if run_dir.exists():
        return run_dir
    raise SystemExit(f"Could not locate probe run at {value}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
