# Audit Report

## Current entry points and flow
- **CLI**: `src/cli.py` exposes `inventory` and `probe_readiness` subcommands built on argparse; inventory delegates to `InventoryRunner`, probe delegates to `run_probe_and_save`.【F:src/cli.py†L10-L122】
- **IDE script**: `src/main.py` is a PyCharm-friendly runner that wraps `InventoryRunner` with editable constants for data root and outputs.【F:src/main.py†L1-L56】
- **Probe helper script**: `scripts/run_probe.py` is a thin wrapper that instantiates `ProbeConfig` and calls `run_probe_and_save` with two constants.【F:scripts/run_probe.py†L1-L17】
- **Streamlit apps**: multipage launcher at `app/Home.py` with pages `app/pages/01_Inventory_QA.py` and `app/pages/02_Probe_QA.py`; legacy single-page dashboard `app/qa_fileimport.py` imports `src` modules directly to visualize inventories.【F:app/qa_fileimport.py†L1-L69】
- **Programmatic runner**: `src/app.py` defines `InventoryRunner` used by CLI and IDE script; it validates inputs, runs the scan, writes artifacts, and appends to `run_log.jsonl`.【F:src/app.py†L1-L103】

## Current data flow
- Inventory uses `scan_inventory` from `src/inventory.py` to walk the file tree, compute hashes, and return `FileRecord` objects.【F:src/inventory.py†L1-L75】
- Outputs are written by `src/manifest.py` as `outputs/inventory.csv`, `outputs/inventory_summary.json`, and `outputs/run_log.jsonl`; no versioned folders or LATEST pointers are created.【F:src/manifest.py†L10-L47】【F:src/manifest.py†L55-L71】
- Probe reads a specific inventory path, lists PDFs, runs readiness checks, then writes `outputs/probes/<timestamp>/` with parquet/CSV plus summary/log files via `src/probe_outputs.py`. The log records the inventory path but no pointer file is kept.【F:src/probe_runner.py†L1-L71】【F:src/probe_outputs.py†L45-L92】
- Streamlit dashboards load artifacts directly from `outputs/` using helpers in `src/io_utils.py` and `src/probe_io.py`, assuming the current flat layout (inventory.csv at root; probe outputs under `outputs/probes/<run_id>`).【F:app/qa_fileimport.py†L10-L41】【F:src/probe_io.py†L32-L62】

## Structural and naming issues
- Package layout is flat under `src/` with many modules; `pyproject.toml` declares the package name as `src` instead of a namespaced package, complicating imports and installs.【F:pyproject.toml†L13-L28】
- Entry points mix relative and absolute imports (`from src...` vs `from .app`), causing confusion and making module execution brittle across contexts.【F:src/cli.py†L5-L7】【F:src/probe_runner.py†L6-L10】
- Scripts live in both `src/` (`main.py`) and `scripts/` (`run_probe.py`), leading to inconsistent locations for PyCharm users.【F:src/main.py†L1-L56】【F:scripts/run_probe.py†L1-L17】
- Inventory and probe logic share path normalization and logging code scattered across modules; no centralized config or utils exist for paths, git metadata, or formatting.【F:src/app.py†L33-L76】【F:src/manifest.py†L55-L71】
- Probe helpers miss necessary imports (`Path`, `json`, `datetime`), so they rely on transitive imports and are fragile; type hints reference undefined names.【F:src/probe_io.py†L1-L45】【F:src/probe_outputs.py†L1-L37】

## Output contract gaps
- Inventory artifacts are unversioned flat files; reruns overwrite previous results and no `LATEST` pointer is written.【F:src/manifest.py†L10-L47】
- Probe outputs include run folders but lack `LATEST.json` pointers and do not record the originating inventory run ID beyond raw path text.【F:src/probe_outputs.py†L45-L92】
- Streamlit pages assume the flat `outputs/inventory.csv` location and do not handle versioned inventory/probe directories, so future reorganizations would break without compatibility layers.【F:app/qa_fileimport.py†L10-L41】【F:app/pages/02_Probe_QA.py†L1-L40】

## Proposed target structure
- Adopt a single package namespace: `src/doj_doc_explorer/` with subpackages for utils, inventory, and probe logic, plus `cli.py` as the canonical interface.
- Move Streamlit multipage app to `app/` with pages that only read stored outputs; keep thin scripts in `scripts/` that call into the package.
- Standardize artifacts:
  - Inventory: `outputs/inventory/<run_id>/inventory.csv`, `inventory_summary.json`, `run_log.json`, and `outputs/inventory/LATEST.json`. Inventory run IDs now incorporate the scanned folder name (sanitized) so download-date roots remain visible in the output path.
  - Probe: `outputs/probes/<run_id>/readiness_pages.parquet|csv`, `readiness_docs.parquet|csv`, `probe_summary.json`, `probe_run_log.json`, plus `outputs/probes/LATEST.json` recording the inventory reference.
- Provide compatibility loaders that can still read legacy `outputs/inventory.csv` and existing probe folders.

## Migration plan
1. Create `src/doj_doc_explorer/` package with `config.py` and utility modules for IO, git metadata, formatting, and logging.
2. Move inventory logic into `inventory/scan.py`, `summarize.py`, and `outputs.py`, preserving existing hashing and summary behavior while adding versioned run IDs and LATEST pointers.
3. Move probe logic into `probe/` modules; centralize run directory handling and ensure logs capture the inventory run ID/path. Fix missing imports and standardize DataFrame writes.
4. Replace argparse CLI with a single `doj_doc_explorer.cli` module supporting `inventory run`, `probe run`, and optional `qa open`; ensure `python -m doj_doc_explorer.cli` works.
5. Add thin PyCharm scripts in `scripts/run_inventory.py` and `scripts/run_probe.py` that edit two constants and delegate to the package.
6. Update Streamlit pages to load artifacts through new loaders that handle both legacy flat outputs and versioned layouts.
7. Rewrite README (and optionally `docs/USAGE.md`) to match the new structure, quickstart, and minimal-input workflows; add troubleshooting and safety notes.
8. Expand tests to cover legacy/new loaders, LATEST pointers, and doc ID determinism; update imports to the new namespace.
9. Ensure `.gitignore` covers `outputs/` and `data/`; add a `self_check` helper under utils.io for quick environment validation.

## Risks and mitigations
- **Backward compatibility**: legacy dashboards might break if loaders are not backward-compatible; mitigate by implementing loader fallbacks and keeping legacy paths readable.
- **Path confusion**: moving scripts could confuse PyCharm run targets; mitigate with clear constants and README guidance.
- **Streamlit performance**: ensure pages only read artifacts without recomputation to avoid slow loads; add caching in loaders where appropriate.
- **Run IDs**: new versioned outputs must be deterministic and timestamp-based to keep histories clear; document formats in README and tests.
