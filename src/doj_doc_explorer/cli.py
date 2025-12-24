from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .config import DEFAULT_OUTPUT_ROOT, InventoryConfig, ProbePaths, ProbeRunConfig
from .inventory.runner import InventoryRunner
from .probe.runner import run_probe_and_save
from .utils.io import latest_inventory, self_check


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
    probe_run.add_argument("--dpi", type=int, default=72, help="Rendering DPI for redaction scan")
    probe_run.add_argument("--text-threshold", type=int, default=25, help="Characters required to mark text")
    probe_run.add_argument("--doc-text-pct-text", type=float, default=0.90, help="Pct of pages with text to call doc text-based")
    probe_run.add_argument("--doc-text-pct-scanned", type=float, default=0.10, help="Pct of pages with text to call doc scanned")
    probe_run.add_argument("--mostly-black", type=float, default=0.90, help="Dark pixel ratio for solid-black pages")
    probe_run.add_argument("--black-intensity", type=int, default=40, help="Grayscale value for black")
    probe_run.add_argument("--adaptive-percentile", type=float, default=10.0, help="Percentile for adaptive cutoff")
    probe_run.add_argument("--mostly-black-adapt", type=float, default=0.90, help="Adaptive ratio threshold (legacy)")
    probe_run.add_argument("--dark-page-median-cutoff", type=float, default=90.0, help="Median grayscale cutoff")
    probe_run.add_argument(
        "--redaction-dark-ratio-min", type=float, default=0.02, help="Minimum dark ratio to flag redaction-like pages"
    )
    probe_run.add_argument(
        "--redaction-contrast-min", type=float, default=30.0, help="Minimum contrast (std dev) to flag redaction-like pages"
    )
    probe_run.add_argument(
        "--redaction-low-contrast-max",
        type=float,
        default=12.0,
        help="Maximum contrast (std dev) to flag uniformly dark pages",
    )
    probe_run.add_argument("--use-center-crop", action="store_true", default=True, help="Enable center crop")
    probe_run.add_argument("--no-center-crop", dest="use_center_crop", action="store_false", help="Disable center crop")
    probe_run.add_argument("--center-crop-pct", type=float, default=0.70, help="Center crop percentage")
    probe_run.add_argument("--max-pdfs", type=int, default=0, help="Limit number of PDFs (0 = all)")
    probe_run.add_argument("--max-pages", type=int, default=0, help="Limit pages per PDF (0 = all)")
    probe_run.add_argument("--skip-black-check", action="store_true", help="Skip redaction scan")
    probe_run.add_argument("--skip-text-check", action="store_true", help="Skip text readiness check")
    probe_run.add_argument("--seed", type=int, default=None, help="Random seed")
    probe_run.add_argument("--only-top-folder", default=None, help="Filter by top-level folder")
    probe_run.set_defaults(func=run_probe_cmd)

    qa = subparsers.add_parser("qa", help="QA helpers")
    qa_sub = qa.add_subparsers(dest="subcommand")
    qa_open = qa_sub.add_parser("open", help="Print Streamlit command")
    qa_open.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT), help="Outputs root")
    qa_open.set_defaults(func=run_qa_open)

    health = subparsers.add_parser("self-check", help="Prepare expected folders")
    health.set_defaults(func=run_self_check)

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
    config = ProbeRunConfig(
        paths=ProbePaths(inventory=inventory_path, outputs_root=outputs_root),
        text_char_threshold=args.text_threshold,
        doc_text_pct_text=args.doc_text_pct_text,
        doc_text_pct_scanned=args.doc_text_pct_scanned,
        fixed_black_intensity=args.black_intensity,
        mostly_black_ratio_fixed=args.mostly_black,
        adaptive_percentile=args.adaptive_percentile,
        mostly_black_ratio_adapt=args.mostly_black_adapt,
        dark_page_median_cutoff=args.dark_page_median_cutoff,
        redaction_dark_ratio_min=args.redaction_dark_ratio_min,
        redaction_contrast_min=args.redaction_contrast_min,
        redaction_low_contrast_max=args.redaction_low_contrast_max,
        render_dpi=args.dpi,
        center_crop_pct=args.center_crop_pct,
        use_center_crop=args.use_center_crop,
        max_pdfs=args.max_pdfs,
        max_pages=args.max_pages,
        skip_black_check=args.skip_black_check,
        skip_text_check=args.skip_text_check,
        seed=args.seed,
        only_top_folder=args.only_top_folder,
    )
    run_dir = run_probe_and_save(config)
    print("Probe run complete")
    print(f"Run dir  : {run_dir}")
    print(f"Summary  : {run_dir / 'probe_summary.json'}")


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


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
