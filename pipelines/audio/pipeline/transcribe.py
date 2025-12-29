from __future__ import annotations

import logging
from typing import Any, Dict, List

LOGGER = logging.getLogger(__name__)


def transcribe_with_whisperx(
    audio_path: str, model_size: str, device: str
) -> Dict[str, Any]:
    """Transcribe audio with whisperX and align word timestamps."""
    try:
        import whisperx  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
        raise ModuleNotFoundError(
            "whisperx is required for transcription. Install requirements.txt."
        ) from exc

    LOGGER.info("Loading WhisperX model=%s device=%s", model_size, device)
    model = whisperx.load_model(model_size, device=device)
    audio = whisperx.load_audio(audio_path)
    LOGGER.info("Running transcription for %s", audio_path)
    result = model.transcribe(audio)

    language = result.get("language", "unknown")
    segments = result.get("segments", [])

    try:
        align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
        aligned = whisperx.align(segments, align_model, metadata, audio, device=device)
        segments = aligned.get("segments", segments)
    except Exception as exc:  # pragma: no cover - alignment is optional
        LOGGER.warning("Alignment failed for %s: %s", audio_path, exc)

    text = " ".join(segment.get("text", "").strip() for segment in segments).strip()
    return {
        "language": language,
        "segments": segments,
        "text": text,
        "model": model_size,
    }

