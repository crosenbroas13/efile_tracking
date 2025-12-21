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

## Run without the terminal (PyCharm-friendly)
If you prefer clicking "Run" in PyCharm instead of typing commands, use the new `src/main.py` entrypoint.

1. Open the project in PyCharm and locate `src/main.py` in the Project tree.
2. Update the constants at the top of the file so they point to your data folder and the output directory you want to use. They default to the repo's gitignored `data/` and `outputs/` folders so you can experiment safely.
3. Right-click `src/main.py` and choose **Run 'main'**. PyCharm will execute the same inventory process as the CLI and print a short summary in the Run tool window.

If you prefer the terminal, you can also launch the IDE entrypoint directly with:

```bash
python src/main.py
```

The script now adjusts its imports automatically so it runs correctly whether you call it as a module (`python -m src.main`) or as a file path. This makes it easier for non-CLI users to try the inventory without extra setup.

If you paste an absolute path into `DEFAULT_DATA_ROOT`, make sure it keeps the leading slash (for example, `/Users/<you>/Documents`). If you accidentally drop that slash, the runner now notices and corrects it when the intended folder exists, so you do not end up scanning the wrong location.

The same guardrails now apply to the output directory: if you paste `Users/<you>/Downloads/Outputs` without the first `/`, the runner automatically fixes it and stores your CSV, summary, and log in the correct folder. Paths printed in the console are also shown as full absolute locations so you always know where the results landed.

Behind the scenes, both the CLI and `main.py` rely on the shared `InventoryRunner` class. That runner bundles the path validation, scanning logic, and logging so you get identical results whether you are in a shell or inside the IDE.

## Project structure
- `src/config.py`: Configuration, ignore rules, and helpers.
- `src/app.py`: `InventoryRunner` and `InventoryResult` for IDE-friendly, programmatic runs.
- `src/inventory.py`: Directory scan, metadata extraction, hashing, and deterministic `file_id` creation.
- `src/manifest.py`: Writes CSV/JSON outputs and builds summaries.
- `src/cli.py`: Argparse entry point for the `inventory` command, now delegating to the shared runner.
- `src/main.py`: Editable entrypoint you can run directly from PyCharm without crafting CLI flags.
- `outputs/`: Default location for reports (gitignored).
- `data/`: Placeholder for datasets (gitignored).

## How to run the QA dashboard
Use the Streamlit dashboard when you want a quick, friendly view of what the inventory captured—no coding required and no document contents loaded. It surfaces totals, file types, folder structure, duplicate hashes, and any obvious red flags (zero-byte files, missing MIME types, unusually large items, and files with timestamps set in the future).

1. Make sure your environment has the app dependencies:
   ```bash
   pip install -e .
   ```
2. Start the local dashboard, pointing it at the folder where your inventory files live (defaults to `./outputs`):
   ```bash
   streamlit run app/qa_dashboard.py -- --out ./outputs
   ```
3. Use the left-hand navigation to open the QA Dashboard (the home page is ready for future tools). Dashboard controls now sit at the top of the page so reviewers can choose an output folder, upload an `inventory.csv` directly from their computer, and adjust the "Very large file" threshold without leaving the main view.
4. The main page shows:
   - **Executive summary** totals for files, sizes, and run-log error counts.
   - **Dataset structure** rollups to see which top-level folders dominate the dataset and which file types are most common.
   - **File type & size QA** tables and charts that highlight unusual extensions or oversized files.
   - **Run history** from `run_log.jsonl` so you can tie the view back to specific inventory runs.
   - **PDF export** button to download a lightweight summary that can be shared with non-technical reviewers without exposing file contents.

The dashboard skips over missing or malformed modified-time values in the CSV so it can still load inventories created on
different machines without breaking.

Everything stays on your machine—perfect for non-technical reviewers who need a quick health check before deeper processing.

If you launch the dashboard straight from a cloned folder without installing the package (`pip install -e .`), the app now adjusts its import path automatically so `src/*` modules still load. That means you can use `streamlit run app/qa_dashboard.py -- --out ./outputs` from the repo root without extra setup.

## Why this helps
This inventory gives a transparent map of what was downloaded—counts, sizes, and file types—without touching document content. The append-only `run_log.jsonl` provides an audit trail for future validation, making it easier to trust the dataset before deeper processing like OCR or parsing.
