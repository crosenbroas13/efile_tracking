# DOJ Document Explorer (Local-First)

This toolkit inventories DOJ document drops and runs light-touch probes to estimate extraction readiness. It is designed to run **locally first**—no external calls, no de-redaction attempts—and to keep outputs versioned for reproducibility.

## Quickstart (five commands)
1. Create and activate a virtual environment.
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install the package (editable mode is fine for local work).
   ```bash
   pip install -e .
   ```
3. Run a self-check to create the expected folders.
   ```bash
   python -m doj_doc_explorer.cli self-check
   ```
4. Run an inventory against your data root (change the path as needed).
   ```bash
   python -m doj_doc_explorer.cli inventory run --root ./data --out ./outputs
   ```
5. Run a probe using the latest inventory.
   ```bash
   python -m doj_doc_explorer.cli probe run --inventory LATEST --out ./outputs
   ```

## Minimal inputs
- **PyCharm scripts**: open `scripts/run_inventory.py` or `scripts/run_probe.py`, edit the two constants at the top (data root/output or inventory/output), and click Run. They now call the same maintained CLI code path, so you can swap between editor-run scripts and terminal commands without worrying about drift.
- **CLI**: stick to the commands above; change only the `--root` or `--inventory` values and the output folder if you want a different location. All entry points are backed by the single `doj_doc_explorer.cli` module to reduce duplicated logic.

## Inventory workflow
- Command: `python -m doj_doc_explorer.cli inventory run --root <DATA_ROOT> --out ./outputs [--hash sha256|md5|sha1|none] [--ignore ...] [--max-files N]`
- Outputs (versioned): `outputs/inventory/<run_id>/inventory.csv`, `inventory_summary.json`, `run_log.json`, plus `outputs/inventory/LATEST.json` pointing at the newest run.
- **Human-friendly run IDs**: the `<run_id>` now starts with the **main folder name you scanned** (sanitized for safe filenames), then the run type and timestamp. This puts the dataset name first so non-technical reviewers can tell which inventory belongs to which drop at a glance.
- Backward compatibility: a copy of `inventory.csv` and `inventory_summary.json` is still written to `outputs/` for older dashboards.
- Deterministic IDs: `file_id` favors the SHA-256 file hash when requested; otherwise it uses the path/size/mtime triple.
- **Large ZIP visibility**: the inventory now reads ZIP file listings without extracting them. Entries appear as `archive.zip::path/inside/file.pdf`, so you can see what is inside oversized archives without opening them manually.

## Probe workflow
- Command: `python -m doj_doc_explorer.cli probe run --inventory <PATH|RUN_ID|LATEST> --out ./outputs [--text-threshold 25] [--doc-text-pct-text 0.50] [--doc-text-min-chars-per-page 200]`
- Outputs (versioned): `outputs/probes/<run_id>/readiness_pages.parquet|csv`, `readiness_docs.parquet|csv`, `probe_summary.json`, `probe_run_log.json`, plus `outputs/probes/LATEST.json` pointing at the latest run and recording the inventory used.
- **Matching probe run IDs**: probe run folders now start with the same **main folder name** captured from the inventory summary, then the run type and timestamp. This keeps inventory and probe outputs aligned for the same dataset.
- Legacy compatibility: probes can still read a flat `outputs/inventory.csv` or a specific run folder.
- ZIP-aware probing: when the inventory lists `archive.zip::path/inside/file.pdf`, the probe extracts **only the PDF entries** into `outputs/probe_extracts/` (or the configured output root) so they can be analyzed without unpacking the full ZIP.
- **Text-based classification now uses two safeguards**:  
  - **50% of pages must have extractable text**, **and**  
  - the file must average at least **200 extractable characters per page**.  
  This two-step rule prevents tiny corner labels on photo-heavy PDFs from being mistaken as real text. In plain terms, it helps reviewers avoid calling a mostly-image document “text-based” just because a small ID tag was detected.
- **Redaction checks are paused**: the current probe run focuses on text readiness only. This avoids dependencies on PDF rendering and keeps the metrics limited to signals we can measure directly (text presence, document classification, and page counts).

## PDF type labeling (rerun-safe)
Use this workflow when you need a human-reviewed PDF type label that stays valid even if you rerun inventory or probe jobs later.

- **Authoritative key**: labels attach to the document’s **relative path (`rel_path`)**, not the derived `doc_id`. This means the label stays attached even if a run ID or hash changes on rerun.
- **Where labels live**: labels are stored in `outputs/labels/pdf_type_labels.csv` and always include the normalized `rel_path`, the **raw label** (`label_raw`), the **normalized label** (`label_norm`), and timestamps.
- **Four-category taxonomy (plain-language)**:
  - **TEXT_PDF**: a PDF that is already text-based.
  - **IMAGE_OF_TEXT_PDF**: a PDF that looks like text but is stored as images (scans).
  - **IMAGE_PDF**: a PDF made of non-text images (photos, forms, drawings).
  - **MIXED_PDF**: a PDF with both real text and image-only pages.
- **Legacy label normalization**: older `TEXT_PDF` entries are normalized to `IMAGE_OF_TEXT_PDF` so that past labels stay consistent with the new taxonomy. This preserves the original entry in `label_raw` while ensuring `label_norm` is consistent for reporting and training.
- **Orphan handling**: if a file disappears in a new inventory, the label is kept but marked as *orphaned* in memory. It will not be used for training or prediction until the file returns, so nothing is silently lost.
- **Safety for reruns**: every labeling, training, and prediction run writes a reconciliation report to `outputs/labels/label_reconciliation_<timestamp>.json`, so non-technical reviewers can see how many labels still match the latest inventory.
- **Friendly labeling UI**: the Streamlit **PDF Labeling** page lets reviewers choose a PDF, apply a label, and save it to the master file without using the command line. This is the easiest path for non-technical reviewers who just need a guided form.
- **Built-in browsing helpers**: the labeling page now includes **search**, **folder-based browsing**, and **sort order** controls so reviewers can quickly locate the next PDF to label without scrolling through long lists.
- **Short-document focus for training**: the labeling UI only lists PDFs with **five pages or fewer** (based on the latest probe run). This keeps the review queue fast and produces a **clean, consistent training set** for future ML models because every label is tied to a compact, easy-to-verify document.
- **Chrome-safe previews**: reviewers see up to **five rendered page images** per PDF instead of an embedded browser PDF, which avoids Chrome iframe restrictions and keeps the review entirely local.

### CLI commands
These commands are designed to show the **relative path** first so reviewers can confirm the correct file.

```bash
# Apply or overwrite a label by relative path.
python -m doj_doc_explorer.cli pdf_type label \
  --inventory LATEST \
  --rel-path "case_folder/scan_001.pdf" \
  --label TEXT_PDF \
  --overwrite

# Preview a safe migration of the labels file (no changes, just a report).
python -m doj_doc_explorer.cli pdf_type migrate \
  --labels outputs/labels/pdf_type_labels.csv \
  --inventory LATEST \
  --dry-run

# Write the migrated labels file (with an automatic backup).
python -m doj_doc_explorer.cli pdf_type migrate \
  --labels outputs/labels/pdf_type_labels.csv \
  --inventory LATEST \
  --write

# Build a training CSV from labels that match the latest inventory.
python -m doj_doc_explorer.cli pdf_type train --inventory LATEST

# Create predictions for unlabeled PDFs using the latest probe run.
python -m doj_doc_explorer.cli pdf_type predict --inventory LATEST --probe LATEST
```

## Streamlit QA dashboards
- Multipage launcher: `streamlit run app/Home.py -- --out ./outputs`. Use `--server.headless true` if you are running on a remote machine and need a URL to connect from your browser.
- Pages read stored artifacts only; they do not rerun inventories or probes. Point them at `./outputs` to pick up the latest versioned runs via `LATEST.json`.
- What you see: the Home page lists available inventories and probe runs. The QA pages chart text readiness, **redaction-like ratios**, and basic file counts so stakeholders can understand what is ready for review without installing Python tools themselves. The Document Filter page adds a table-driven view for narrowing to long, low-text, or flagged files, and the Probe Run Comparison page highlights differences between two probe runs so teams can explain what changed over time. The Probe Document Viewer supports **relative path search** and a **Chrome-safe image preview** mode so reviewers can jump directly to a file even if embedded PDF previews are blocked.
- Data handling: Streamlit reads only from your local `outputs/` folder and never uploads files. You can safely share screenshots or exported charts because the app avoids transmitting underlying documents.
- Troubleshooting: if Streamlit cannot find data, rerun `python -m doj_doc_explorer.cli self-check` to create expected folders, then rerun an inventory or probe. The CLI will print the exact command needed to launch the dashboards with your chosen output path.

## Outputs and versioning
- `outputs/inventory/`: versioned inventory runs plus `LATEST.json`.
- `outputs/probes/`: versioned probe runs plus `LATEST.json` referencing the inventory path.
- `outputs/labels/`: PDF type labels, reconciliation reports, training snapshots, and predictions.
- `outputs/run_index.json`: a **centralized “latest run” index** keyed by the original dataset folder you scanned. Each entry records the most recent inventory **and** probe run for that dataset so repeated runs update one place without overwriting history.
- `outputs/inventory.csv` and `outputs/inventory_summary.json` remain for older tooling; new code prefers versioned folders.

## Troubleshooting
- **Missing inventory**: `probe run` with `LATEST` will fail if no inventory exists; run an inventory first.
- **Encrypted or unreadable PDFs**: they are logged in the run log and skipped; probes continue.
- **Windows/Mac absolute paths**: the CLI resolves `~` and relative paths; prefer absolute paths if you keep datasets outside the repo.
- **Missing dependencies**: ensure `pip install -e .` completed; `pyarrow` is used when present for parquet outputs.
- **Redaction metrics**: redaction scans are currently disabled, so you will not see redaction ratios or redaction warnings in the dashboards.

## Safety statement
- No network calls or telemetry are made.
- No attempts are made to reverse redactions; probes only record numeric readiness metrics.
- All computations run locally; outputs stay on disk for auditability.

## Repository file guide
Use this checklist to understand what lives where. It is written in plain language so project managers and analysts can see how the pieces fit together without reading code.

- **Project metadata**
  - `.gitattributes`: Keeps text files normalized so Git diffs stay predictable across operating systems.
  - `.gitignore`: Prevents temporary data (such as outputs or virtual environments) from being committed.
  - `pyproject.toml`: Defines the Python package name, dependencies, and build settings.
  - `docs/AUDIT_REPORT.md`: A narrative audit of entry points, data flow, and migration plans for the toolkit.

- **Helper scripts**
  - `scripts/run_inventory.py`: Simple entry point for IDE users; edit two constants to scan a folder and write inventory outputs.
  - `scripts/run_probe.py`: IDE-friendly probe launcher that locates the latest inventory (or a specific run ID) and saves readiness metrics.

- **Streamlit dashboards**
  - `app/Home.py`: Landing page that introduces the dashboards and explains how to navigate them safely.
  - `app/qa_fileimport.py`: Main Streamlit view for browsing inventories, highlighting potential issues, and exporting a PDF summary.
  - `app/pages/01_Inventory_QA.py`: Thin wrapper that hosts the inventory QA view inside the multipage app.
  - `app/pages/02_Probe_QA.py`: Probe results viewer with charts and download buttons for the readiness metrics.
  - `app/pages/03_Probe_Run_Compare.py`: Side-by-side comparison page for two probe runs, highlighting shifts in totals, document-level readiness, and **non-PDF inventory file types** (so reviewers can see if new spreadsheets, images, or text files were added between runs).
  - `app/pages/04_Document_Filter.py`: Filterable document table that merges probe outputs with inventory metadata so reviewers can quickly spot long, low-text, or unusual files without opening the PDFs.
  - `app/pages/04_Probe_Document_Viewer.py`: Single-document preview page with relative path search and alternate image previews for PDF files.
  - `app/pages/05_Text_Based_Documents.py`: Focused view for **100% text-based** PDFs, showing the latest text-ready share as a pie chart and pairing each PDF preview with its extracted text so reviewers can quickly confirm what is ready for immediate analysis. The preview toggle includes a **Chrome-safe rendered image** option, which is helpful when embedded PDFs are blocked in a browser or when sharing with non-technical reviewers who need a quick visual check without downloading files.
  - `app/pages/06_PDF_Labeling.py`: Guided labeling workspace for PDF type review. It **only lists PDFs up to five pages** (using the latest probe run’s page counts) and renders up to five page images so non-technical reviewers can label quickly without opening an embedded PDF viewer.

- **Core package (`src/` folder)**
  - `src/__init__.py`: Exposes the `InventoryRunner` and result dataclass for simple imports.
  - `src/main.py`: PyCharm-friendly runner that triggers inventories using editable constants for paths and settings.
  - `src/app.py`: Implements `InventoryRunner`, handling path validation, inventory execution, summaries, and logging.
  - `src/config.py`: Dataclass for inventory configuration plus helpers to normalize and apply ignore patterns.
  - `src/inventory.py`: Walks the dataset, gathers file metadata and hashes, and also lists files inside ZIP archives without extracting them.
  - `src/manifest.py`: Writes inventory CSVs, JSON summaries, and run logs to disk.
  - `src/cli.py`: Legacy wrapper that routes CLI calls to the maintained `doj_doc_explorer.cli` module while keeping old behavior.
  - `src/io_utils.py`: Shared loaders for inventory CSVs, summaries, and run logs with optional Streamlit caching.
  - `src/qa_metrics.py`: Computes executive summaries, file rollups, and issue detection from inventory data.
  - `src/git_utils.py`: Utility for capturing the current Git commit hash in run logs.
  - `src/probe_config.py`: Configuration dataclass for probe runs, including thresholds and sampling settings.
  - `src/probe_readiness.py`: Reads PDFs to estimate text readiness, classify documents, and track errors.
  - `src/probe_blackpages.py`: Legacy redaction scanner (currently unused while redaction checks are paused).
  - `src/probe_runner.py`: Orchestrates readiness checks, merges results, and collects run metadata.
  - `src/probe_outputs.py`: Saves probe outputs (CSV/Parquet plus summaries and logs) to versioned run folders.
  - `src/probe_io.py`: Loads probe runs from disk and lists available runs for dashboard use.
  - `src/probe_viz_helpers.py`: Small formatting and parsing helpers used by the Probe QA dashboard.
  - `src/doj_doc_explorer/pdf_type/labels.py`: Rerun-safe PDF type labeling utilities (label storage, reconciliation, and rel_path normalization).
  - `src/doj_doc_explorer/utils/paths.py`: Shared helper for normalizing relative paths so labels match inventories across reruns.

- **Tests**
  - `tests/conftest.py`: Ensures the repository root is importable during testing.
  - `tests/test_app.py`: Validates that `InventoryRunner` resolves input and output paths correctly.
  - `tests/test_cli.py`: Checks CLI error handling and verifies inventory outputs are created.
  - `tests/test_inventory.py`: Covers inventory scanning behavior, file ID stability, and summary aggregation.
  - `tests/test_probe_io.py`: Confirms probe run discovery and loading logic for stored probe results.
  - `tests/test_probes.py`: Exercises PDF classification and deterministic document IDs.
  - `tests/test_qa_metrics.py`: Verifies categorization, duplicate detection, and issue flagging heuristics for inventory data.
