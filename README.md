# DOJ Dataset Inventory Starter

This starter project builds a local-first inventory for the DOJ document explorer. It scans a root folder that already contains your downloaded public datasets (six top-level folders, potentially with nested files) and produces lightweight, auditable manifests. Only file metadata is collected—content is never parsed or altered.

## What this tool does
- Walks the dataset directory, respecting optional ignore patterns and symlink rules.
- Captures file metadata: relative/absolute paths, sizes, timestamps, extensions, and best-effort MIME detection.
- Computes configurable hashes (none, MD5, SHA-1, SHA-256) and optional sample hashes for quick checks.
- Writes three artifacts in `outputs/`:
  - `inventory.csv`: one row per file with metadata and hashes.
  - `inventory_summary.json`: totals, counts by extension/MIME, largest files, and folder rollups.
  - `run_log.jsonl`: append-only log of each run with arguments, timing, errors, and git commit (if available).
- Handles unreadable files gracefully: they are logged, and the scan continues.

## Quick start (friendly version)
1. **Install Python 3.10+** on your machine.
2. **Create a virtual environment (recommended for a clean setup):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
3. **Install the project and test tools:**
   ```bash
   pip install -e .
   pip install -e .[test]  # optional: lets you run pytest
   ```
4. **Prepare a folder with files to scan.** If you just want to try the tool, make a tiny sample:
   ```bash
   mkdir -p sample_data
   echo "hello" > sample_data/example.txt
   ```
5. **Run an inventory in one command:**
   ```bash
   python -m src.cli inventory --root "./sample_data" --out "./outputs"
   ```
   The command will validate that your `--root` exists and is a folder before scanning. Progress details (hash algorithm, output folder, and file cap) print before the walk begins.

## How to run an inventory (customized)
The CLI uses a single `inventory` command. Replace `<PATH_TO_DATA_ROOT>` with the folder containing the six top-level DOJ dataset folders (or your own sample directory).

```bash
python -m src.cli inventory \
  --root "<PATH_TO_DATA_ROOT>" \
  --out "./outputs" \
  --hash sha256 \
  --sample-bytes 0
```

### Common options (plain English)
- `--ignore`: Skip files or folders matching these glob patterns (can repeat). Defaults already skip system files like `*.DS_Store`.
- `--follow-symlinks`: Follow symlinks during the walk (off by default so you do not accidentally scan huge linked folders).
- `--max-files`: Safety cap on the number of files to process. The CLI now refuses non-positive values so the limit is always meaningful.
- `--hash`: `none`, `md5`, `sha1`, or `sha256` (default).
- `--sample-bytes`: If greater than zero, also compute a hash of the first N bytes for a quick comparison while still recording full sizes.

### Outputs explained
- `inventory.csv`: Deterministic `file_id` per file (hash of path, size, modified time), plus metadata and hashes. A `sample_hash` is present when requested.
- `inventory_summary.json`: Counts files and bytes, groups by extension and MIME, surfaces the top 10 largest files, and rolls up by top-level folder.
- `run_log.jsonl`: One JSON object per run with timestamps, CLI arguments, file counts, errors, and git commit (if this repo is a git checkout).

### Safety and performance notes
- Files are hashed in streaming chunks to avoid loading large files into memory.
- Permission errors or unreadable files are recorded and do not stop the scan.
- Set `--hash none` for the fastest run; use `--sample-bytes` to get lightweight fingerprints without full hashing.

## Testing
Everything is wired to `pytest` so you can confirm the basics quickly:
- Make sure your virtual environment is active (`source .venv/bin/activate`).
- Install test dependencies: `pip install -e .[test]`.
- Run the suite:
  ```bash
  pytest
  ```
The tests exercise the CLI pre-checks (missing folders, wrong paths, and invalid `--max-files` values) and verify that running against a tiny sample folder writes all three output files.

## Project structure
- `src/config.py`: Configuration, ignore rules, and helpers.
- `src/inventory.py`: Directory scan, metadata extraction, hashing, and deterministic `file_id` creation.
- `src/manifest.py`: Writes CSV/JSON outputs and builds summaries.
- `src/cli.py`: Argparse entry point for the `inventory` command.
- `outputs/`: Default location for reports (gitignored).
- `data/`: Placeholder for datasets (gitignored).

## Why this helps
This inventory gives a transparent map of what was downloaded—counts, sizes, and file types—without touching document content. The append-only `run_log.jsonl` provides an audit trail for future validation, making it easier to trust the dataset before deeper processing like OCR or parsing.
