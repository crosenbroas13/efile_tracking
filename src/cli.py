import argparse
import subprocess
import time
from pathlib import Path

from .config import InventoryConfig, normalize_patterns
from .inventory import scan_inventory
from .manifest import append_run_log, build_summary, write_inventory_csv, write_summary_json


def _git_commit() -> str:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return commit
    except Exception:
        return "unknown"


def run_inventory(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    out_dir = Path(args.out).expanduser()
    config = InventoryConfig(
        root=root,
        out_dir=out_dir,
        hash_algorithm=args.hash,
        sample_bytes=args.sample_bytes,
        ignore_patterns=normalize_patterns(args.ignore),
        follow_symlinks=args.follow_symlinks,
        max_files=args.max_files,
    )
    start = time.time()
    records, errors = scan_inventory(config)
    csv_path = write_inventory_csv(records, out_dir)
    summary = build_summary(records)
    summary_path = write_summary_json(summary, out_dir)
    runtime = time.time() - start
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(root),
        "args": {
            "hash": args.hash,
            "sample_bytes": args.sample_bytes,
            "ignore": args.ignore,
            "follow_symlinks": args.follow_symlinks,
            "max_files": args.max_files,
        },
        "runtime_seconds": runtime,
        "files_scanned": len(records),
        "errors_count": len(errors),
        "git_commit": _git_commit(),
        "errors": errors,
    }
    append_run_log(log_entry, out_dir)
    print(f"Inventory complete: {csv_path}")
    print(f"Summary written: {summary_path}")
    if errors:
        print(f"Encountered {len(errors)} issues; see run_log.jsonl for details.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dataset inventory and manifest CLI")
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
