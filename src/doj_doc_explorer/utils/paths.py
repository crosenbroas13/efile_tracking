from __future__ import annotations

import re


_VOLUME_FOLDER_RE = re.compile(r"^VOL\d{5}$", re.IGNORECASE)


def normalize_rel_path(path: str) -> str:
    if path is None:
        return ""
    value = str(path).strip()
    if not value:
        return ""
    value = value.replace("\\", "/")
    if "::" in value:
        prefix, suffix = value.split("::", 1)
        return f"{_normalize_segment(prefix)}::{_normalize_segment(suffix)}"
    return _normalize_segment(value)


def _normalize_segment(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    while cleaned.startswith("/"):
        cleaned = cleaned[1:]
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    return "/".join(parts)

def top_level_folder_from_rel_path(rel_path: str) -> str:
    if not rel_path:
        return ""
    normalized = normalize_rel_path(rel_path)
    prefix = normalized.split("::", 1)[0]
    parts = [part for part in prefix.split("/") if part]
    for part in parts:
        if _VOLUME_FOLDER_RE.match(part):
            return part.upper()
    return parts[0] if parts else ""


__all__ = ["normalize_rel_path", "top_level_folder_from_rel_path"]
