from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def safe_pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def format_pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def parse_datetime(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def safe_series(df: pd.DataFrame, column: str, fill_value: Any) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([fill_value] * len(df))


__all__ = ["safe_pct", "format_pct", "parse_datetime", "safe_series"]
