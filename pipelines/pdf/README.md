# PDF pipeline (follow-on processing)

This folder is a **guidepost** for PDF-specific steps that build on the base pipeline.
The implementation lives in the package under `src/doj_doc_explorer/`:

- `src/doj_doc_explorer/pdf_type/`: labeling utilities and reconciliation helpers.
- `src/doj_doc_explorer/classification/doc_type/`: doc-type model features + training.
- `src/doj_doc_explorer/text_scan/`: text-quality and content-type scanning.

Use the CLI commands documented in the main README to run these steps after you
complete the base inventory + probe.
