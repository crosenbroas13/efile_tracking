from __future__ import annotations

from datetime import datetime
import re


def sanitize_run_label(value: str | None) -> str | None:
    if not value:
        return None
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "root"


def new_run_id(prefix: str, label: str | None = None) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sanitized_label = sanitize_run_label(label)
    if sanitized_label:
        return f"{sanitized_label}_{prefix}_{timestamp}"
    return f"{prefix}_{timestamp}"


__all__ = ["sanitize_run_label", "new_run_id"]
