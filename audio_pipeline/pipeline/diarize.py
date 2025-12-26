from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)


def diarize_segments(
    audio_path: str,
    segments: List[Dict[str, Any]],
    device: str,
    hf_token: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[int]]:
    """Run speaker diarization and attach speaker labels to segments."""
    try:
        import whisperx  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
        raise ModuleNotFoundError(
            "whisperx is required for diarization. Install requirements.txt."
        ) from exc

    LOGGER.info("Running diarization for %s", audio_path)
    diarization_pipeline = whisperx.DiarizationPipeline(
        use_auth_token=hf_token,
        device=device,
    )
    diarization_result = diarization_pipeline(audio_path)
    segments_with_speakers = whisperx.assign_word_speakers(diarization_result, segments)

    rttm_lines = []
    for segment in diarization_result.itertracks(yield_label=True):
        turn, _, speaker = segment
        rttm_lines.append(
            f"SPEAKER {audio_path} 1 {turn.start:.3f} {turn.duration:.3f} <NA> <NA> {speaker} <NA> <NA>"
        )
    rttm_content = "\n".join(rttm_lines) if rttm_lines else None
    num_speakers = len({label for _, _, label in diarization_result.itertracks(yield_label=True)})
    return segments_with_speakers, rttm_content, num_speakers

