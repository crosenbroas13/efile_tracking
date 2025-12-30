# Name Mentions Index (Public-Safe)

The **Name Mentions Index** is a local-only, public-safe index of person-name mentions found in
**VERIFIED GOOD text PDFs**. It stores **counts and page numbers only**—no extracted text or snippets.

## What is indexed (plain language)
- **Who appears**: person-name-like patterns such as **“First Last”** or **“Last, First.”**
- **Where they appear**: which document and which page numbers.
- **How often they appear**: counts per page and total counts per document.
- **Search variants**: the index supports **“first last,” “last first,” and “last, first”** lookups.

## What is NOT stored
- **No raw text** from the PDFs.
- **No snippets** or surrounding context.
- **No OCR** output for scanned/image PDFs.

## Limitations (plain language)
- **Scanned image PDFs won’t work** without OCR because this index only uses text that is already
  extractable.
- **Conservative name detection**: the index uses heuristics, not machine learning, so it may miss
  unusual names or skip ALL-CAPS headings.

## How to run
```bash
python -m doj_doc_explorer.cli name_index run \
  --inventory LATEST \
  --probe LATEST \
  --text-scan LATEST \
  --out ./outputs
```

### Optional filters
- `--only-verified-good / --no-only-verified-good` (default: on)
- `--min-total-count 1`
- `--max-names-per-doc 500`

## Outputs (versioned)
Each run is stored under `outputs/name_index/<run_id>/` and `outputs/name_index/LATEST.json`
points to the newest run.

- `name_index.jsonl` — full index records (one record per name)
- `public_name_index.json` — lightweight public export (no internal variants)
- `name_index_summary.json` — counts and run configuration
- `name_index_run_log.json` — audit log with configuration + error summary

## Streamlit testing view (mock)
Use the Streamlit **Name Search (Mock)** page to review the layout and workflow without running
the full pipeline yet. It ships with sample data so non-technical reviewers can validate
search, filters, and CSV export before you publish a real name index. The page now includes a
**name dropdown** (so you can jump straight to a specific person) and a **Search** button that
locks in the current filters, which helps reviewers understand exactly why the results changed.

## Public site name search (plain language)
The `docs/name-search.html` page is the public-facing version of the name lookup. It now offers a
**name dropdown** plus a **Search** button so visitors can pick a person and know when the results
are refreshed. This avoids confusion when typing because results only update after they submit.

Launch the dashboards and open **Name Search (Mock)** from the sidebar:
```bash
streamlit run analysis/streamlit/Home.py
```

## Why this matters (plain language)
This index helps non-technical reviewers answer **“where does this name appear?”** without
exposing document text. It provides **searchable metadata** while keeping sensitive content
on disk and out of the index.
