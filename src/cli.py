import argparse
import time
from pathlib import Path

from .app import InventoryRunner
from .probe_config import ProbeConfig
from .probe_runner import run_probe_and_save


def run_inventory(args: argparse.Namespace) -> None:
    runner = InventoryRunner()
    try:
        config = runner.create_config(
            root=Path(args.root),
            out_dir=Path(args.out),
            hash_algorithm=args.hash,
            sample_bytes=args.sample_bytes,
            ignore_patterns=args.ignore,
            follow_symlinks=args.follow_symlinks,
            max_files=args.max_files,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    start = time.time()
    print(
        "Starting scan...\n"
        f"  Data folder: {config.root}\n"
        f"  Outputs -> {config.out_dir}\n"
        f"  Hash algorithm: {config.hash_algorithm} (sample bytes: {config.sample_bytes})\n"
        f"  Max files: {'no limit' if config.max_files is None else config.max_files}"
    )

    result = runner.run(config)
    runtime = time.time() - start

    print(f"Inventory complete: {result.csv_path}")
    print(f"Summary written: {result.summary_path}")
    print(f"Files scanned: {len(result.records)} in {runtime:.2f}s")
    if result.errors:
        print(f"Encountered {len(result.errors)} issues; see run_log.jsonl for details.")


def run_probe_cli(args: argparse.Namespace) -> None:
    config = ProbeConfig(
        inventory_path=Path(args.inventory),
        output_root=Path(args.out),
        text_char_threshold=args.text_threshold,
        doc_text_pct_text=args.doc_text_pct_text,
        doc_text_pct_scanned=args.doc_text_pct_scanned,
        fixed_black_intensity=args.black_intensity,
        mostly_black_ratio_fixed=args.mostly_black,
        adaptive_percentile=args.adaptive_percentile,
        mostly_black_ratio_adapt=args.mostly_black_adapt,
        dark_page_median_cutoff=args.dark_page_median_cutoff,
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
    print(f"Probe run complete -> {run_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dataset inventory and manifest CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    inv = subparsers.add_parser("inventory", help="Scan a dataset directory")
    inv.add_argument("--root", required=True, help="Dataset root folder")
    inv.add_argument("--out", default="./outputs", help="Output folder")
    inv.add_argument("--hash", default="sha256", choices=["none", "md5", "sha1", "sha256"], help="Hash algorithm")
    inv.add_argument("--sample-bytes", dest="sample_bytes", type=int, default=0, help="Sample size for partial hash")
    inv.add_argument("--ignore", action="append", default=[], help="Glob patterns to ignore (can repeat)")
    inv.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks during scan")
    inv.add_argument("--max-files", type=int, default=None, help="Optional safety limit on number of files")
    inv.set_defaults(func=run_inventory)

    probe = subparsers.add_parser("probe_readiness", help="Run extraction readiness probe")
    probe.add_argument("--inventory", default="./outputs/inventory.csv", help="Path to inventory CSV")
    probe.add_argument("--out", default="./outputs", help="Output folder root")
    probe.add_argument("--dpi", type=int, default=72, help="Rendering DPI for black-page check")
    probe.add_argument("--text-threshold", type=int, default=25, help="Characters required to mark a page as containing text")
    probe.add_argument("--doc-text-pct-text", type=float, default=0.90, help="Pct of pages with text to call doc text-based")
    probe.add_argument("--doc-text-pct-scanned", type=float, default=0.10, help="Pct of pages with text to call doc scanned")
    probe.add_argument("--mostly-black", type=float, default=0.90, help="Black pixel ratio threshold")
    probe.add_argument("--black-intensity", type=int, default=40, help="Grayscale value to count as black (0-255)")
    probe.add_argument("--adaptive-percentile", type=float, default=10.0, help="Percentile used for adaptive darkness cutoff")
    probe.add_argument("--mostly-black-adapt", type=float, default=0.90, help="Adaptive ratio threshold for dark pages")
    probe.add_argument("--dark-page-median-cutoff", type=float, default=90.0, help="Median grayscale cutoff for dark-page rule")
    probe.add_argument("--use-center-crop", action="store_true", default=True, help="Enable center crop for black detection")
    probe.add_argument("--no-center-crop", action="store_false", dest="use_center_crop", help="Disable center crop evaluation")
    probe.add_argument("--center-crop-pct", type=float, default=0.70, help="Portion of center used for crop")
    probe.add_argument("--max-pdfs", type=int, default=0, help="Limit number of PDFs (0 means all)")
    probe.add_argument("--max-pages", type=int, default=0, help="Limit pages per PDF (0 means all)")
    probe.add_argument("--skip-black-check", action="store_true", help="Skip black-page evaluation")
    probe.add_argument("--skip-text-check", action="store_true", help="Skip text readiness check")
    probe.add_argument("--seed", type=int, default=None, help="Random seed for sampling")
    probe.add_argument("--only-top-folder", default=None, help="Filter by top_level_folder value")
    probe.set_defaults(func=run_probe_cli)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
