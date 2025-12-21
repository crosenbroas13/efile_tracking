import argparse
import time
from pathlib import Path

from .app import InventoryRunner


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
