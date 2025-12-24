from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class TextQualityConfig:
    empty_min_chars: int = 50
    empty_min_words: int = 10
    min_alpha_ratio: float = 0.45
    min_printable_ratio: float = 0.95
    max_gibberish: float = 0.60
    gibberish_min_words: int = 30
    gibberish_symbol_ratio: float = 0.45
    repeated_run_min: int = 4
    repeated_run_ratio: float = 0.12
    snippet_max_chars: int = 200

    def as_dict(self) -> Dict[str, object]:
        return {
            "empty_min_chars": self.empty_min_chars,
            "empty_min_words": self.empty_min_words,
            "min_alpha_ratio": self.min_alpha_ratio,
            "min_printable_ratio": self.min_printable_ratio,
            "max_gibberish": self.max_gibberish,
            "gibberish_min_words": self.gibberish_min_words,
            "gibberish_symbol_ratio": self.gibberish_symbol_ratio,
            "repeated_run_min": self.repeated_run_min,
            "repeated_run_ratio": self.repeated_run_ratio,
            "snippet_max_chars": self.snippet_max_chars,
        }


@dataclass
class TextScanRunConfig:
    inventory_path: Path
    probe_run_dir: Path
    outputs_root: Path
    max_docs: int = 0
    max_pages: int = 0
    min_text_pages: int = 1
    seed: int = 42
    store_snippet: bool = False
    quality: TextQualityConfig = field(default_factory=TextQualityConfig)

    @property
    def run_args(self) -> Dict[str, object]:
        return {
            "inventory_path": str(self.inventory_path),
            "probe_run_dir": str(self.probe_run_dir),
            "outputs_root": str(self.outputs_root),
            "max_docs": self.max_docs,
            "max_pages": self.max_pages,
            "min_text_pages": self.min_text_pages,
            "seed": self.seed,
            "store_snippet": self.store_snippet,
            "quality": self.quality.as_dict(),
        }


__all__ = ["TextQualityConfig", "TextScanRunConfig"]
