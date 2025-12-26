from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4"}
ZIP_EXTENSION = ".zip"


@dataclass(frozen=True)
class DiscoveredMedia:
    media_path: Path
    display_path: str
    display_name: str
    output_label: str


def _safe_zip_entry_path(entry_name: str) -> Path:
    entry = PurePosixPath(entry_name)
    parts = [part for part in entry.parts if part not in ("", ".", "..")]
    return Path(*parts) if parts else Path("entry")


def _zip_extract_dir(zip_path: Path, extract_root: Path) -> Path:
    digest = hashlib.sha256(str(zip_path).encode("utf-8")).hexdigest()[:8]
    return extract_root / f"{zip_path.stem}_{digest}"


def _sanitize_output_label(value: str) -> str:
    sanitized = []
    for char in value.strip():
        if char.isalnum() or char in ("-", "_"):
            sanitized.append(char)
        else:
            sanitized.append("_")
    label = "".join(sanitized).strip("_")
    return label or "media_file"


def _extract_zip_entry(
    archive: zipfile.ZipFile,
    zip_path: Path,
    entry_name: str,
    info: zipfile.ZipInfo,
    extract_root: Path,
) -> Path:
    safe_entry = _safe_zip_entry_path(entry_name)
    extract_dir = _zip_extract_dir(zip_path, extract_root)
    target_path = extract_dir / safe_entry
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and target_path.stat().st_size == info.file_size:
        return target_path
    with archive.open(info) as source, target_path.open("wb") as target:
        shutil.copyfileobj(source, target)
    return target_path


def _discover_zip_media(zip_path: Path, extract_root: Path) -> list[DiscoveredMedia]:
    discovered: list[DiscoveredMedia] = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                entry_name = info.filename
                entry_suffix = Path(entry_name).suffix.lower()
                if entry_suffix not in SUPPORTED_EXTENSIONS:
                    continue
                extracted = _extract_zip_entry(archive, zip_path, entry_name, info, extract_root)
                entry_path = Path(entry_name)
                label_source = f"{zip_path.stem}__{entry_path.with_suffix('').as_posix()}"
                discovered.append(
                    DiscoveredMedia(
                        media_path=extracted,
                        display_path=f"{zip_path}::{entry_name}",
                        display_name=entry_path.name,
                        output_label=_sanitize_output_label(label_source),
                    )
                )
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        LOGGER.warning("Failed to read zip archive %s: %s", zip_path, exc)
    return discovered


def discover_media_files(root: Path, extract_root: Path) -> list[DiscoveredMedia]:
    if not root.exists():
        raise FileNotFoundError(f"Input path does not exist: {root}")
    extract_root.mkdir(parents=True, exist_ok=True)
    discovered: list[DiscoveredMedia] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS:
            discovered.append(
                DiscoveredMedia(
                    media_path=path,
                    display_path=str(path),
                    display_name=path.name,
                    output_label=_sanitize_output_label(path.stem),
                )
            )
        elif suffix == ZIP_EXTENSION:
            discovered.extend(_discover_zip_media(path, extract_root))
    return sorted(discovered, key=lambda item: item.display_path)


def safe_output_dir(output_root: Path, output_label: str) -> Path:
    sanitized_name = _sanitize_output_label(output_label)
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
