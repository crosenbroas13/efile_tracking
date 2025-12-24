from __future__ import annotations


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


__all__ = ["normalize_rel_path"]
