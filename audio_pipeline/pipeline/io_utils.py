from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4"}


def discover_media_files(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"Input path does not exist: {root}")
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def safe_output_dir(output_root: Path, file_path: Path) -> Path:
    sanitized_name = file_path.stem.replace(" ", "_")
    return output_root / sanitized_name


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def probe_duration_seconds(path: Path) -> Optional[float]:
    """Use ffprobe to get duration in seconds if available."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        return float(output) if output else None
    except (subprocess.SubprocessError, FileNotFoundError, ValueError) as exc:
        LOGGER.debug("ffprobe duration lookup failed for %s: %s", path, exc)
        return None


def limit_files(paths: Iterable[Path], max_files: Optional[int]) -> list[Path]:
    paths_list = list(paths)
    if max_files is None or max_files <= 0:
        return paths_list
    return paths_list[:max_files]

