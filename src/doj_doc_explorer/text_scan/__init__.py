from __future__ import annotations

from .config import TextQualityConfig, TextScanRunConfig

__all__ = ["TextQualityConfig", "TextScanRunConfig", "run_text_scan", "run_text_scan_and_save"]


def __getattr__(name: str):
    if name in {"run_text_scan", "run_text_scan_and_save"}:
        from .runner import run_text_scan, run_text_scan_and_save

        return {"run_text_scan": run_text_scan, "run_text_scan_and_save": run_text_scan_and_save}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
