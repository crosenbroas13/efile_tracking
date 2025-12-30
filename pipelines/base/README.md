# Base pipeline (inventory + probe)

The **base pipeline** is the shared starting point for every DOJ pull folder. It handles
ingestion, inventory, and readiness probing before any specialized processing
begins. For clarity in run IDs and dashboards, name the top-level folder with the
pull date (for example, `DOJ_DataSets_12.23.25`).

## What lives here
- `scripts/run_inventory.py`: edit two constants and run a local inventory.
- `scripts/run_probe.py`: edit two constants and run a probe on the latest inventory.
- `doj_disclosures_downloader.py`: optional networked downloader for the DOJ disclosure page.

## Typical flow (plain language)
1. Inventory your DOJ pull folder (counts + metadata).
2. Probe PDFs for text readiness (what is likely searchable).
3. Hand off to the PDF or audio pipelines as needed.
