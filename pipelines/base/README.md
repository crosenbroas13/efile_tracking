# Base pipeline (inventory + probe)

The **base pipeline** is the shared starting point for every dataset. It handles
ingestion, inventory, and readiness probing before any specialized processing
begins.

## What lives here
- `scripts/run_inventory.py`: edit two constants and run a local inventory.
- `scripts/run_probe.py`: edit two constants and run a probe on the latest inventory.
- `doj_disclosures_downloader.py`: optional networked downloader for the DOJ disclosure page.

## Typical flow (plain language)
1. Inventory your dataset (counts + metadata).
2. Probe PDFs for text readiness (what is likely searchable).
3. Hand off to the PDF or audio pipelines as needed.
