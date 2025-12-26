from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from pipeline.config import InventoryConfig
from pipeline.diarize import diarize_segments
from pipeline.features import extract_features
from pipeline.index_writer import append_index_row, build_meta_payload, write_json, write_text
from pipeline.io_utils import (
    compute_sha256,
    discover_media_files,
    ensure_dir,
    limit_files,
    probe_duration_seconds,
    safe_output_dir,
)
from pipeline.transcribe import transcribe_with_whisperx


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected true/false value.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-only audio inventory pipeline.")
    parser.add_argument("--input", required=True, type=Path, help="Input folder of media files.")
    parser.add_argument("--output", required=True, type=Path, help="Output folder for artifacts.")
    parser.add_argument("--model", default="base", help="Whisper model size (base, small, medium).")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Device type.")
    parser.add_argument("--diarize", type=parse_bool, default=False, help="Enable diarization.")
    parser.add_argument("--hf_token", default=None, help="Hugging Face token for diarization.")
    parser.add_argument("--overwrite", type=parse_bool, default=False, help="Overwrite existing outputs.")
    parser.add_argument("--max_files", type=int, default=None, help="Limit files for dry runs.")
    parser.add_argument("--log_level", default="INFO", help="Log level (INFO, DEBUG).")
    parser.add_argument("--config", type=Path, default=None, help="Optional JSON/YAML config.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = InventoryConfig.load(args.config)
    config.model_size = args.model
    config.device = args.device
    config.diarize = args.diarize
    config.hf_token = args.hf_token
    config.overwrite = args.overwrite
    config.max_files = args.max_files
    config.log_level = args.log_level

    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
    logger = logging.getLogger("audio_pipeline")

    ensure_dir(args.output)
    index_path = args.output / "index.csv"

    media_files = limit_files(discover_media_files(args.input), config.max_files)
    logger.info("Discovered %s media files", len(media_files))

    summary = {"processed": 0, "skipped": 0, "failed": 0}

    for media_path in media_files:
        output_dir = safe_output_dir(args.output, media_path)
        ensure_dir(output_dir)
        transcript_path = output_dir / "transcript.txt"
        segments_path = output_dir / "segments.json"
        meta_path = output_dir / "meta.json"
        diarization_path = output_dir / "diarization.rttm"

        if output_dir.exists() and not config.overwrite and transcript_path.exists():
            append_index_row(
                index_path,
                {
                    "file_path": str(media_path),
                    "file_name": media_path.name,
                    "sha256": compute_sha256(media_path),
                    "duration_sec": probe_duration_seconds(media_path),
                    "language": None,
                    "word_count": None,
                    "num_segments": None,
                    "num_speakers": None,
                    "top_keywords": None,
                    "email_count": None,
                    "phone_count": None,
                    "date_like_count": None,
                    "transcript_path": str(transcript_path),
                    "segments_path": str(segments_path),
                    "meta_path": str(meta_path),
                    "status": "SKIPPED",
                    "error_message": "Output exists and overwrite=false.",
                },
            )
            summary["skipped"] += 1
            continue

        warnings: List[str] = []
        row: Dict[str, Any] = {
            "file_path": str(media_path),
            "file_name": media_path.name,
            "sha256": compute_sha256(media_path),
            "duration_sec": probe_duration_seconds(media_path),
            "language": None,
            "word_count": None,
            "num_segments": None,
            "num_speakers": None,
            "top_keywords": None,
            "email_count": None,
            "phone_count": None,
            "date_like_count": None,
            "transcript_path": str(transcript_path),
            "segments_path": str(segments_path),
            "meta_path": str(meta_path),
            "status": "OK",
            "error_message": "",
        }

        try:
            transcription = transcribe_with_whisperx(
                str(media_path), config.model_size, config.device
            )
            segments = transcription["segments"]
            text = transcription["text"]

            if config.diarize:
                try:
                    segments, rttm_content, num_speakers = diarize_segments(
                        str(media_path), segments, config.device, config.hf_token
                    )
                    if rttm_content:
                        write_text(diarization_path, rttm_content)
                    row["num_speakers"] = num_speakers
                except Exception as exc:
                    warnings.append(f"Diarization failed: {exc}")
            else:
                row["num_speakers"] = None

            features = extract_features(text, config.keywords)

            write_text(transcript_path, text)
            write_json(segments_path, {"segments": segments})

            meta_payload = build_meta_payload(
                {
                    "file_path": str(media_path),
                    "language": transcription.get("language"),
                    "model": transcription.get("model"),
                    "word_count": features["word_count"],
                    "num_segments": len(segments),
                    "features": features,
                },
                warnings,
                config.to_dict(),
            )
            write_json(meta_path, meta_payload)

            row.update(
                {
                    "language": transcription.get("language"),
                    "word_count": features["word_count"],
                    "num_segments": len(segments),
                    "top_keywords": ",".join(features["top_keywords"]),
                    "email_count": features["email_count"],
                    "phone_count": features["phone_count"],
                    "date_like_count": features["date_like_count"],
                }
            )

            summary["processed"] += 1
        except Exception as exc:
            row["status"] = "FAILED"
            row["error_message"] = str(exc)
            summary["failed"] += 1
            logger.exception("Failed processing %s", media_path)

        append_index_row(index_path, row)

    logger.info(
        "Run summary: processed=%s skipped=%s failed=%s",
        summary["processed"],
        summary["skipped"],
        summary["failed"],
    )
    summary_path = args.output / "run_summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


if __name__ == "__main__":
    main()
