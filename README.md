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
- **PyCharm scripts**: open `scripts/run_inventory.py` or `scripts/run_probe.py`, edit the two constants at the top (data root/output or inventory/output), and click Run. They delegate to the same package code as the CLI.
- **CLI**: stick to the commands above; change only the `--root` or `--inventory` values and the output folder if you want a different location.

## Inventory workflow
- Command: `python -m doj_doc_explorer.cli inventory run --root <DATA_ROOT> --out ./outputs [--hash sha256|md5|sha1|none] [--ignore ...] [--max-files N]`
- Outputs (versioned): `outputs/inventory/<run_id>/inventory.csv`, `inventory_summary.json`, `run_log.json`, plus `outputs/inventory/LATEST.json` pointing at the newest run.
- Backward compatibility: a copy of `inventory.csv` and `inventory_summary.json` is still written to `outputs/` for older dashboards.
- Deterministic IDs: `file_id` favors the SHA-256 file hash when requested; otherwise it uses the path/size/mtime triple.

## Probe workflow
- Command: `python -m doj_doc_explorer.cli probe run --inventory <PATH|RUN_ID|LATEST> --out ./outputs [--dpi 72] [--text-threshold 25] [--mostly-black 0.90]`
- Outputs (versioned): `outputs/probes/<run_id>/readiness_pages.parquet|csv`, `readiness_docs.parquet|csv`, `probe_summary.json`, `probe_run_log.json`, plus `outputs/probes/LATEST.json` pointing at the latest run and recording the inventory used.
- Legacy compatibility: probes can still read a flat `outputs/inventory.csv` or a specific run folder.

## Streamlit QA dashboards
- Multipage launcher: `streamlit run app/Home.py -- --out ./outputs`
- Pages read stored artifacts only; they do not rerun inventories or probes. Point them at `./outputs` to pick up the latest versioned runs via `LATEST.json`.

## Outputs and versioning
- `outputs/inventory/`: versioned inventory runs plus `LATEST.json`.
- `outputs/probes/`: versioned probe runs plus `LATEST.json` referencing the inventory path.
- `outputs/inventory.csv` and `outputs/inventory_summary.json` remain for older tooling; new code prefers versioned folders.

## Troubleshooting
- **Missing inventory**: `probe run` with `LATEST` will fail if no inventory exists; run an inventory first.
- **Encrypted or unreadable PDFs**: they are logged in the run log and skipped; probes continue.
- **Windows/Mac absolute paths**: the CLI resolves `~` and relative paths; prefer absolute paths if you keep datasets outside the repo.
- **Missing dependencies**: ensure `pip install -e .` completed; `pyarrow` is used when present for parquet outputs.

## Safety statement
- No network calls or telemetry are made.
- No attempts are made to reverse redactions; probes only record numeric readiness metrics and black-page ratios.
- All computations run locally; outputs stay on disk for auditability.
