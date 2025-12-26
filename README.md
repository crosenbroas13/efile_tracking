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

## DOJ disclosure downloader (networked)
Use this script when you need to **mirror the official DOJ disclosure page** onto your local disk for later review.

```bash
python doj_disclosures_downloader.py
```

### What it does (plain language)
- **Finds only the file links** inside the DOJ disclosure accordion and downloads those ZIP/PDF/MP4/WAV files.
- **Keeps a local manifest** so it does *not* re-download unchanged files.
- **Writes a rotating log** so non-technical reviewers can see what changed between runs.

### Why this matters
- **Predictable storage**: everything lands under `outputs/doj_disclosures/`, organized by the DOJ section heading so reviewers can browse by topic.
- **Low risk of duplicates**: the manifest tracks `etag`, `last_modified`, and file size, reducing storage waste.
- **Network awareness**: this is one of the few tools in the repo that **does** make external requests (to justice.gov), so run it only when you intend to pull fresh files.

### Helpful options
- `--dry-run`: list what would download without saving files. This still updates the manifest with link metadata, but it **does not calculate file checksums** because nothing is downloaded.
- `--watch 30`: recheck every 30 minutes until you stop it.
- `--limit 5`: cap downloads per run for safe testing.

## Inventory workflow
- Command: `python -m doj_doc_explorer.cli inventory run --root <DATA_ROOT> --out ./outputs [--hash sha256|md5|sha1|none] [--ignore ...] [--max-files N]`
- Outputs (versioned): `outputs/inventory/<run_id>/inventory.csv`, `inventory_summary.json`, `run_log.json`, plus `outputs/inventory/LATEST.json` pointing at the newest run.
- **Human-friendly run IDs**: the `<run_id>` now starts with the **main folder name you scanned** (sanitized for safe filenames), then the run type and timestamp. This puts the dataset name first so non-technical reviewers can tell which inventory belongs to which drop at a glance.
- Backward compatibility: a copy of `inventory.csv` and `inventory_summary.json` is still written to `outputs/` for older dashboards.
- Deterministic IDs: `file_id` favors the SHA-256 file hash when requested; otherwise it uses the path/size/mtime triple.
- **Large ZIP visibility**: the inventory now reads ZIP file listings without extracting them. Entries appear as `archive.zip::path/inside/file.pdf`, so you can see what is inside oversized archives without opening them manually.

## Probe workflow
- Command: `python -m doj_doc_explorer.cli probe run --inventory <PATH|RUN_ID|LATEST> --out ./outputs [--text-threshold 25] [--doc-text-pct-text 0.50] [--doc-text-min-chars-per-page 200] [--run-text-scan/--no-run-text-scan]`
- Outputs (versioned): `outputs/probes/<run_id>/readiness_pages.parquet|csv`, `readiness_docs.parquet|csv`, `probe_summary.json`, `probe_run_log.json`, plus `outputs/probes/LATEST.json` pointing at the latest run and recording the inventory used.
- **Matching probe run IDs**: probe run folders now start with the same **main folder name** captured from the inventory summary, then the run type and timestamp. This keeps inventory and probe outputs aligned for the same dataset.
- Legacy compatibility: probes can still read a flat `outputs/inventory.csv` or a specific run folder.
- ZIP-aware probing: when the inventory lists `archive.zip::path/inside/file.pdf`, the probe extracts **only the PDF entries** into `outputs/probe_extracts/` (or the configured output root) so they can be analyzed without unpacking the full ZIP.
- **Text-based classification now uses two safeguards**:  
  - **50% of pages must have extractable text**, **and**  
  - the file must average at least **200 extractable characters per page**.  
  This two-step rule prevents tiny corner labels on photo-heavy PDFs from being mistaken as real text. In plain terms, it helps reviewers avoid calling a mostly-image document “text-based” just because a small ID tag was detected.
- **Text Scan runs inside the probe by default**: after the probe identifies likely text-based PDFs, it immediately performs a **Text Scan** to measure text quality and content type. This helps reviewers separate **verified, searchable text** from PDFs that only *pretend* to have usable text. Use `--no-run-text-scan` if you want to skip the text scan step during probing.
- **Redaction checks are paused**: the current probe run focuses on text readiness only. This avoids dependencies on PDF rendering and keeps the metrics limited to signals we can measure directly (text presence, document classification, and page counts).
- **Doc-type final decision (human-first)**: the probe now writes `doc_type_final` for each PDF using a simple priority:  
  **TRUTH** (your label) → **MODEL** (if confidence ≥ 0.70) → **HEURISTIC** (the legacy rule).  
  This makes it easy for non-technical reviewers to see *why* a document type was chosen, and it keeps human labels authoritative when they exist.
- **Doc-type model usage flags**:  
  - `--use-doc-type-model / --no-doc-type-model` to toggle ML usage.  
  - `--model LATEST|PATH|MODEL_ID` to select the model.  
  - `--min-model-confidence 0.70` to control when model predictions are trusted.

## Text Scan (Text Quality + Content Type)
The **Text Scan** step checks PDFs that *appear* text-based and measures whether the extracted text is actually usable. It also predicts a **high-level content type** (email, legal filing, memo, etc.) so reviewers can triage faster. **No full text is stored**—only numeric quality signals, category predictions, and minimal rule-hit counts.

### Why this matters (plain language)
- **Catches “fake text” PDFs**: Some PDFs have empty or junk text layers that pass simple “has text” rules. Text Scan flags these so reviewers can relabel them as **IMAGE_OF_TEXT_PDF** instead of treating them as ready-to-search text.
- **Adds context for reviewers**: Content type predictions help non-technical reviewers prioritize emails vs. legal filings vs. financial docs without opening every file.

### CLI command
```bash
python -m doj_doc_explorer.cli text_scan run --inventory LATEST --probe LATEST --out ./outputs
```

### When to use the standalone command
- **Rerun with different thresholds**: if you want stricter or looser text-quality settings than the probe defaults.
- **Rescan after updates**: if you relabel or repair PDFs and want fresh text-quality signals without rerunning the entire probe.

### Outputs
- `outputs/text_scan/<run_id>/doc_text_signals.parquet|csv`
- `outputs/text_scan/<run_id>/text_scan_summary.json`
- `outputs/text_scan/<run_id>/text_scan_run_log.json`
- `outputs/text_scan/LATEST.json`

### Streamlit impact
The **Text Based Documents** page now merges Text Scan signals so it can:
- Confirm **verified text** PDFs (GOOD text quality),
- Provide a **content type breakdown** for text-ready documents,
- Keep the view focused on *already-usable* text for non-technical reviewers.

The **PDF Labeling** page now includes the **suspicious text-layer queue** (EMPTY/LOW quality), so reviewers can
download a labeling list and relabel those PDFs as **IMAGE_OF_TEXT_PDF** in the same workflow.

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
- **Suspicious text-layer queue included**: PDFs with empty/low-quality text layers now appear here (with a one-click CSV download), so reviewers can immediately relabel them instead of switching to another page.
- **Verified text excluded**: PDFs already confirmed as **GOOD** text quality are filtered out of the labeling list and progress tables to keep reviewers focused on documents that still need a PDF type decision.

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

## Doc-type model (trained from your labels)
This workflow turns human labels into a **doc-type classifier** that can distinguish:
**TEXT_PDF**, **IMAGE_OF_TEXT_PDF**, **IMAGE_PDF**, and **MIXED_PDF**. It is designed for **CPU-only, local-only** runs and stores **numeric features only** (no extracted text or saved page images).

### Dependencies (plain language)
- **Optional on purpose**: the core inventory and probe steps run without extra PDF-rendering libraries.  
- **Required for ML features**: to train or run the doc-type model, install **PyMuPDF** (this provides the `fitz` module).  
  ```bash
  pip install PyMuPDF
  ```
  If you accidentally installed the unrelated `fitz` package, uninstall it first so the correct dependency is used:
  ```bash
  pip uninstall fitz
  ```

### Why this matters (plain language)
- **Scanned text vs. photos** are easy to confuse with simple “has text” rules.  
  The ML model uses lightweight image statistics (entropy, edges, projection variance) to separate scanned text from photo-heavy PDFs.
- **Human labels stay in control**. If a document is labeled, the probe will always use the label as the final doc type.

### CLI commands
```bash
# Train a doc-type model from human labels + probe metrics.
python -m doj_doc_explorer.cli doc_type train \
  --inventory LATEST \
  --probe LATEST \
  --labels outputs/labels/pdf_type_labels.csv \
  --out ./outputs

# Predict doc types for selected docs (optionally only unlabeled).
python -m doj_doc_explorer.cli doc_type predict \
  --inventory LATEST \
  --probe LATEST \
  --model LATEST \
  --out ./outputs \
  --only-unlabeled

# Queue the lowest-confidence docs for the next labeling batch.
python -m doj_doc_explorer.cli doc_type queue \
  --inventory LATEST \
  --probe LATEST \
  --model LATEST \
  --k 200 \
  --out ./outputs
```

## Streamlit QA dashboards
- Multipage launcher: `streamlit run app/Home.py -- --out ./outputs`. Use `--server.headless true` if you are running on a remote machine and need a URL to connect from your browser.
- **Set the output folder once**: to avoid retyping the output path on each page, set `DOJ_OUTPUT_DIR` (or pass `-- --out ...`) before you launch Streamlit. See [docs/STREAMLIT_OUTPUT_SETUP.md](docs/STREAMLIT_OUTPUT_SETUP.md) for a short, non-technical walkthrough.
- Pages read stored artifacts only; they do not rerun inventories or probes. Point them at `./outputs` to pick up the latest versioned runs via `LATEST.json`.
- **Local-first reminder:** the dashboards can run straight from this repo without a separate install step because the app loads modules from the `src/` folder. If you prefer a traditional install, `pip install -e .` still works the same.
- **Home page (executive snapshot):** the landing view now auto-loads the *latest inventory and probe* and presents a **non-technical summary**:
  - **Executive Summary**: total file count and total size (quick scale check).
  - **Dataset Structure**: a pie chart of file share by top-level folder plus a **Top 5 largest folders** table (so reviewers see where storage is concentrated).
  - **Files by Type**: a stacked bar chart of file counts by extension with top-level folders as the legend (to highlight format mix by source).
  - **Text Based PDF Documents**: counts of probe text-based PDFs, verified-good vs. suspicious text layers, and the overall share of text-based PDFs in the inventory (so reviewers know what is ready for immediate search vs. needs OCR).
- What you see on other pages: the QA pages chart text readiness, **redaction-like ratios**, and basic file counts so stakeholders can understand what is ready for review without installing Python tools themselves. The Document Filter page adds a table-driven view for narrowing to long, low-text, or flagged files, and the Probe Run Comparison page highlights differences between two probe runs so teams can explain what changed over time. The Probe Document Viewer supports **relative path search** and a **Chrome-safe image preview** mode so reviewers can jump directly to a file even if embedded PDF previews are blocked.
- Data handling: Streamlit reads only from your local `outputs/` folder and never uploads files. You can safely share screenshots or exported charts because the app avoids transmitting underlying documents.
- Troubleshooting: if Streamlit cannot find data, rerun `python -m doj_doc_explorer.cli self-check` to create expected folders, then rerun an inventory or probe. The CLI will print the exact command needed to launch the dashboards with your chosen output path.

## Outputs and versioning
- `outputs/inventory/`: versioned inventory runs plus `LATEST.json`.
- `outputs/probes/`: versioned probe runs plus `LATEST.json` referencing the inventory path.
- `outputs/text_scan/`: text-quality and content-type scans plus `LATEST.json`.
- `outputs/labels/`: PDF type labels, reconciliation reports, training snapshots, and predictions.
- `outputs/models/doc_type/`: trained doc-type classifiers (`model.joblib`, `model_card.json`, `training_snapshot.csv`).
- `outputs/classification/doc_type/`: prediction runs (`doc_type_predictions.csv`) created by the `doc_type predict` command.
- `outputs/run_index.json`: a **centralized “latest run” index** keyed by the original dataset folder you scanned. Each entry records the most recent inventory **and** probe run for that dataset so repeated runs update one place without overwriting history.
- `outputs/inventory.csv` and `outputs/inventory_summary.json` remain for older tooling; new code prefers versioned folders.

## Troubleshooting
- **Missing inventory**: `probe run` with `LATEST` will fail if no inventory exists; run an inventory first.
- **Encrypted or unreadable PDFs**: they are logged in the run log and skipped; probes continue.
- **Windows/Mac absolute paths**: the CLI resolves `~` and relative paths; prefer absolute paths if you keep datasets outside the repo.
- **Missing dependencies**: ensure `pip install -e .` completed; `pyarrow` is used when present for parquet outputs.
- **`fitz` / `static/` errors**: these usually mean the wrong `fitz` package is installed.  
  Uninstall `fitz` and install **PyMuPDF** instead (see the doc-type model dependency note above).  
  The probe and Streamlit previews now detect this mismatch and give a clear fix message so non-technical users
  know why image previews or doc-type features are unavailable until PyMuPDF is installed.
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
  - `doj_disclosures_downloader.py`: Networked downloader that mirrors the DOJ Epstein disclosure accordion into `outputs/doj_disclosures/` with a manifest to avoid re-downloading unchanged files.

- **Streamlit dashboards**
  - `app/Home.py`: Landing page that introduces the dashboards and explains how to navigate them safely.
  - `app/qa_fileimport.py`: Main Streamlit view for browsing inventories, highlighting potential issues, and exporting a PDF summary.
  - `app/pages/01_Inventory_QA.py`: Thin wrapper that hosts the inventory QA view inside the multipage app.
  - `app/pages/02_Probe_QA.py`: Probe results viewer with charts and download buttons for the readiness metrics.
  - `app/pages/03_Probe_Run_Compare.py`: Side-by-side comparison page for two probe runs, highlighting shifts in totals, document-level readiness, and **non-PDF inventory file types** (so reviewers can see if new spreadsheets, images, or text files were added between runs).
- `app/pages/04_Document_Filter.py`: Filterable document table that merges probe outputs with inventory metadata so reviewers can quickly spot long, low-text, or unusual files without opening the PDFs.
- `app/pages/04_Probe_Document_Viewer.py`: Single-document preview page with relative path search and alternate image previews for PDF files.
- `app/pages/05_Text_Based_Documents.py`: Focused view for **text-based PDFs** that now blends probe results with **Text Scan** quality signals. It separates **verified text** from **suspicious text layers**, shows **content type breakdowns**, and provides CSV exports for labeling queues. The preview toggle includes a **Chrome-safe rendered image** option, which is helpful when embedded PDFs are blocked in a browser or when sharing with non-technical reviewers who need a quick visual check without downloading files.
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
  - `src/text_scan_io.py`: Loads text-scan runs and merges text quality signals into dashboards.
  - `src/doj_doc_explorer/pdf_type/labels.py`: Rerun-safe PDF type labeling utilities (label storage, reconciliation, and rel_path normalization).
  - `src/doj_doc_explorer/text_scan/`: Text Scan pipeline (quality metrics, content type rules, and run outputs).
  - `src/doj_doc_explorer/classification/doc_type/features.py`: Numeric, page-sampled features (fonts, images, and thumbnail statistics) used for doc-type ML.
  - `src/doj_doc_explorer/classification/doc_type/model.py`: Training, saving, and inference helpers for doc-type classification.
  - `src/doj_doc_explorer/utils/paths.py`: Shared helper for normalizing relative paths so labels match inventories across reruns.

- **Tests**
  - `tests/conftest.py`: Ensures the repository root is importable during testing.
  - `tests/test_app.py`: Validates that `InventoryRunner` resolves input and output paths correctly.
  - `tests/test_cli.py`: Checks CLI error handling and verifies inventory outputs are created.
  - `tests/test_inventory.py`: Covers inventory scanning behavior, file ID stability, and summary aggregation.
  - `tests/test_probe_io.py`: Confirms probe run discovery and loading logic for stored probe results.
  - `tests/test_probes.py`: Exercises PDF classification and deterministic document IDs.
  - `tests/test_qa_metrics.py`: Verifies categorization, duplicate detection, and issue flagging heuristics for inventory data.
