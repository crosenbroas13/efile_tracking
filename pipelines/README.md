# Pipelines overview (plain language)

This folder groups **all ingestion and processing steps** into one place so the flow is easy to follow.
Start with the **base pipeline** (inventory + probe), then branch into the specialized pipelines.

## How the pipelines fit together
1. **Base pipeline**: the shared starting point for all datasets.
2. **PDF pipeline**: PDF-specific follow-on steps such as labeling, doc-type modeling, and text scan review.
3. **Audio pipeline**: local-only transcription + diarization inventory for audio/video files.
4. **Other pipeline**: reserved for future non-PDF, non-audio workflows.

## Directory guide
- `pipelines/base/`: inventory + probe scripts and the DOJ disclosure downloader.
- `pipelines/pdf/`: PDF processing guides (the implementation lives in `src/doj_doc_explorer/pdf_type/`).
- `pipelines/audio/`: audio inventory pipeline (includes its own README and optional dependencies).
- `pipelines/other/`: placeholder for future pipelines.
