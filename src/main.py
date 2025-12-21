"""Simple entrypoint for running inventories directly from an IDE.

Update the constants in this file to point at your data folder and
preferred output directory, then click "Run" in PyCharm. Everything is
executed through the shared ``InventoryRunner`` so the same validation
and outputs are used whether you call the CLI or this script.
"""
from pathlib import Path

from .app import InventoryRunner

# Edit these values to match your machine. They default to the repo's
# gitignored ``data`` and ``outputs`` folders so you can test safely.
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_OUTPUT_DIR = Path("outputs")
DEFAULT_HASH = "sha256"
DEFAULT_SAMPLE_BYTES = 0
DEFAULT_IGNORE = []  # e.g., ["*.tmp", "**/scratch/*"]
FOLLOW_SYMLINKS = False
MAX_FILES = None  # Set to a positive integer to stop after N files


def main() -> None:
    runner = InventoryRunner()
    config = runner.create_config(
        root=DEFAULT_DATA_ROOT,
        out_dir=DEFAULT_OUTPUT_DIR,
        hash_algorithm=DEFAULT_HASH,
        sample_bytes=DEFAULT_SAMPLE_BYTES,
        ignore_patterns=DEFAULT_IGNORE,
        follow_symlinks=FOLLOW_SYMLINKS,
        max_files=MAX_FILES,
    )
    result = runner.run(config)

    print("\nInventory finished")
    print("------------------")
    print(f"Data folder : {config.root}")
    print(f"Outputs     : {config.out_dir}")
    print(f"Files       : {len(result.records)}")
    print(f"Errors      : {len(result.errors)} (see run_log.jsonl for details)")
    print(f"CSV         : {result.csv_path}")
    print(f"Summary     : {result.summary_path}")
    print(f"Run log     : {result.log_path}")
    print(f"Runtime     : {result.runtime_seconds:.2f}s")


if __name__ == "__main__":
    main()
