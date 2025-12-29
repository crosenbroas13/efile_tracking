# Local-Only Audio Inventory Pipeline

This module provides a **local-only** audio transcription + optional speaker diarization pipeline designed for **unknown content discovery**. It scans a folder of audio/video files (including **audio inside ZIP archives**), produces structured artifacts per file, and writes a global `index.csv` so you can later organize or classify the files based on what they contain.

## Local-Only Principles
- **No external API calls.** Everything runs locally on your machine.
- **Model downloads are opt-in.** If you enable diarization or choose a larger model, third-party weights may be downloaded on the first run. This is explicit and documented below.

## Project Layout
```
pipelines/audio/
  run_inventory.py
  pipeline/
    config.py
    io_utils.py
    transcribe.py
    diarize.py
    features.py
    index_writer.py
    exceptions.py
  outputs/
  requirements.txt
  README.md
```

## Install (Local-Only)
> Recommended: use a virtual environment.
```
python -m venv .venv
source .venv/bin/activate
pip install -e ".[audio]"
```

If you prefer the standalone requirements file, run:
```
pip install -r pipelines/audio/requirements.txt
```

**System dependency:** `ffmpeg` / `ffprobe` should be available on your PATH for duration detection.

## Run the Inventory
```
python pipelines/audio/run_inventory.py --input /path/to/media --output /path/to/output
```

### Example (CPU-friendly)
```
python pipelines/audio/run_inventory.py --input ./samples --output ./outputs --model base --device cpu
```

### Dry Run / Small Batch
```
python pipelines/audio/run_inventory.py --input ./samples --output ./outputs --max_files 3
```

## Optional Diarization (Explicit Opt-In)
Diarization uses `pyannote.audio` via WhisperX. This may require **Hugging Face model downloads**, which are **opt-in** and **local** once cached.

```
python pipelines/audio/run_inventory.py --input ./samples --output ./outputs --diarize true --hf_token YOUR_TOKEN
```

If you do **not** want external downloads, leave diarization disabled.

## Output Artifacts (Per File)
Each input file creates a folder under the output directory:
```
output/<file_stem>/
  transcript.txt
  segments.json
  meta.json
  diarization.rttm   (optional)
```
**ZIP entries:** when audio is found inside a ZIP, the pipeline extracts **only the audio files** into `output/zip_extracts/` and records the original location as `archive.zip::path/inside/file.ext` in `index.csv` and `meta.json`. This keeps the audit trail intact without unpacking the entire archive.

### `index.csv` (Global Inventory)
The pipeline writes `output/index.csv` with one row per file:
- file_path, file_name, sha256, duration_sec
- language, word_count, num_segments, num_speakers (if available)
- top_keywords, email_count, phone_count, date_like_count
- transcript_path, segments_path, meta_path
- status (OK/FAILED/SKIPPED), error_message

## Discovery Features
The pipeline extracts lightweight signals for unknown-content discovery:
- **word_count**
- **keyword hits** (configurable categories)
- **regex counts**: emails, phone numbers, URLs, date-like patterns
- **structure hints**: e.g., `from:`, `subject:`, `case number`, `invoice`, `thank you for calling`

These are stored in `meta.json` and surfaced in `index.csv`.

## Configuration (Optional)
Use JSON or YAML to define defaults (e.g., keywords):
```
{
  "model_size": "base",
  "device": "cpu",
  "diarize": false,
  "keywords": {
    "legal": ["deposition", "plaintiff", "defendant"],
    "finance": ["invoice", "wire", "payment"]
  }
}
```
Run with:
```
python pipelines/audio/run_inventory.py --input ./samples --output ./outputs --config config.json
```

## CPU Runtime Notes
- **Base** or **small** models are recommended for CPU-only environments.
- Larger models are slower and may require more memory.
