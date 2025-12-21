from __future__ import annotations

from datetime import datetime


def human_bytes(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def percent(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100


def iso_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


__all__ = ["human_bytes", "percent", "iso_now"]
