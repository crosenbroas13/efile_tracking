from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict

from .config import TextQualityConfig


_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")


@dataclass
class TextStats:
    total_chars: int
    total_words: int
    avg_chars_per_text_page: float
    avg_words_per_text_page: float
    alpha_ratio: float
    digit_ratio: float
    printable_ratio: float
    unique_char_ratio: float
    avg_line_len: float
    std_line_len: float
    control_char_count: int
    replacement_char_count: int
    repeated_run_score: float
    gibberish_score: float
    text_quality_score: float
    text_quality_label: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "total_chars": self.total_chars,
            "total_words": self.total_words,
            "avg_chars_per_text_page": self.avg_chars_per_text_page,
            "avg_words_per_text_page": self.avg_words_per_text_page,
            "alpha_ratio": self.alpha_ratio,
            "digit_ratio": self.digit_ratio,
            "printable_ratio": self.printable_ratio,
            "unique_char_ratio": self.unique_char_ratio,
            "avg_line_len": self.avg_line_len,
            "std_line_len": self.std_line_len,
            "control_char_count": self.control_char_count,
            "replacement_char_count": self.replacement_char_count,
            "repeated_run_score": self.repeated_run_score,
            "gibberish_score": self.gibberish_score,
            "text_quality_score": self.text_quality_score,
            "text_quality_label": self.text_quality_label,
        }


class TextAccumulator:
    def __init__(self, config: TextQualityConfig) -> None:
        self.config = config
        self.total_chars = 0
        self.total_words = 0
        self.non_whitespace = 0
        self.alpha_count = 0
        self.digit_count = 0
        self.printable_count = 0
        self.unique_chars: set[str] = set()
        self.control_char_count = 0
        self.replacement_char_count = 0
        self.line_len_sum = 0
        self.line_len_sq_sum = 0
        self.line_count = 0
        self.repeated_run_chars = 0

    def update(self, text: str) -> None:
        if not text:
            return
        self.total_chars += len(text)
        self.total_words += len(text.split())
        self.unique_chars.update(text)

        for line in text.splitlines():
            length = len(line.strip())
            self.line_len_sum += length
            self.line_len_sq_sum += length**2
            self.line_count += 1

        prev_char: str | None = None
        run_len = 0
        for char in text:
            if char == "\ufffd":
                self.replacement_char_count += 1
            if char.isspace():
                if char.isprintable():
                    self.printable_count += 1
            else:
                self.non_whitespace += 1
                if char.isalpha():
                    self.alpha_count += 1
                elif char.isdigit():
                    self.digit_count += 1
                if char.isprintable():
                    self.printable_count += 1
                else:
                    self.control_char_count += 1

            if prev_char is None or char != prev_char:
                if (
                    run_len >= self.config.repeated_run_min
                    and prev_char is not None
                    and not prev_char.isalnum()
                    and not prev_char.isspace()
                ):
                    self.repeated_run_chars += run_len
                run_len = 1
                prev_char = char
            else:
                run_len += 1

        if (
            run_len >= self.config.repeated_run_min
            and prev_char is not None
            and not prev_char.isalnum()
            and not prev_char.isspace()
        ):
            self.repeated_run_chars += run_len

    def finalize(self, text_pages_scanned: int) -> TextStats:
        total_chars = self.total_chars
        total_words = self.total_words
        avg_chars_per_text_page = (total_chars / text_pages_scanned) if text_pages_scanned else 0.0
        avg_words_per_text_page = (total_words / text_pages_scanned) if text_pages_scanned else 0.0

        alpha_ratio = (self.alpha_count / self.non_whitespace) if self.non_whitespace else 0.0
        digit_ratio = (self.digit_count / self.non_whitespace) if self.non_whitespace else 0.0
        printable_ratio = (self.printable_count / total_chars) if total_chars else 0.0
        unique_char_ratio = (len(self.unique_chars) / total_chars) if total_chars else 0.0

        if self.line_count:
            avg_line_len = self.line_len_sum / self.line_count
            variance = max((self.line_len_sq_sum / self.line_count) - avg_line_len**2, 0.0)
            std_line_len = math.sqrt(variance)
        else:
            avg_line_len = 0.0
            std_line_len = 0.0

        repeated_run_score = (self.repeated_run_chars / total_chars) if total_chars else 0.0
        gibberish_score = _compute_gibberish_score(
            alpha_ratio=alpha_ratio,
            printable_ratio=printable_ratio,
            total_words=total_words,
            total_chars=total_chars,
            non_whitespace=self.non_whitespace,
            digit_ratio=digit_ratio,
            replacement_char_count=self.replacement_char_count,
            control_char_count=self.control_char_count,
            repeated_run_score=repeated_run_score,
            config=self.config,
        )

        text_quality_label = _quality_label(
            total_chars=total_chars,
            total_words=total_words,
            alpha_ratio=alpha_ratio,
            printable_ratio=printable_ratio,
            gibberish_score=gibberish_score,
            config=self.config,
        )
        text_quality_score = _quality_score(alpha_ratio, printable_ratio, total_words, gibberish_score)

        return TextStats(
            total_chars=total_chars,
            total_words=total_words,
            avg_chars_per_text_page=avg_chars_per_text_page,
            avg_words_per_text_page=avg_words_per_text_page,
            alpha_ratio=alpha_ratio,
            digit_ratio=digit_ratio,
            printable_ratio=printable_ratio,
            unique_char_ratio=unique_char_ratio,
            avg_line_len=avg_line_len,
            std_line_len=std_line_len,
            control_char_count=self.control_char_count,
            replacement_char_count=self.replacement_char_count,
            repeated_run_score=repeated_run_score,
            gibberish_score=gibberish_score,
            text_quality_score=text_quality_score,
            text_quality_label=text_quality_label,
        )


def sanitize_snippet(text: str, config: TextQualityConfig) -> str:
    if not text:
        return ""
    snippet = " ".join(text.split())
    snippet = _EMAIL_RE.sub("[email]", snippet)
    snippet = _LONG_NUMBER_RE.sub("[number]", snippet)
    if len(snippet) > config.snippet_max_chars:
        snippet = snippet[: config.snippet_max_chars].rstrip() + "…"
    return snippet


def _quality_label(
    *,
    total_chars: int,
    total_words: int,
    alpha_ratio: float,
    printable_ratio: float,
    gibberish_score: float,
    config: TextQualityConfig,
) -> str:
    if total_chars < config.empty_min_chars or total_words < config.empty_min_words:
        return "EMPTY"
    if (
        gibberish_score >= config.max_gibberish
        or alpha_ratio < config.min_alpha_ratio
        or printable_ratio < config.min_printable_ratio
    ):
        return "LOW"
    return "GOOD"


def _quality_score(alpha_ratio: float, printable_ratio: float, total_words: int, gibberish_score: float) -> float:
    word_score = min(total_words / 200, 1.0)
    base = 0.5 * alpha_ratio + 0.3 * printable_ratio + 0.2 * word_score
    score = max(min(base * (1 - gibberish_score), 1.0), 0.0)
    return float(score)


def _compute_gibberish_score(
    *,
    alpha_ratio: float,
    printable_ratio: float,
    total_words: int,
    total_chars: int,
    non_whitespace: int,
    digit_ratio: float,
    replacement_char_count: int,
    control_char_count: int,
    repeated_run_score: float,
    config: TextQualityConfig,
) -> float:
    if total_chars == 0:
        return 0.0
    symbol_count = max(non_whitespace - int(alpha_ratio * non_whitespace) - int(digit_ratio * non_whitespace), 0)
    symbol_ratio = (symbol_count / non_whitespace) if non_whitespace else 0.0

    score = 0.0
    if alpha_ratio < config.min_alpha_ratio:
        score += 0.35
    if printable_ratio < config.min_printable_ratio:
        score += 0.15
    if total_words < config.gibberish_min_words and total_chars >= config.empty_min_chars:
        score += 0.15
    if symbol_ratio > config.gibberish_symbol_ratio:
        score += 0.15
    if replacement_char_count > 0:
        score += 0.1
    if control_char_count > 0:
        score += 0.1
    if repeated_run_score >= config.repeated_run_ratio:
        score += 0.15
    return float(min(score, 1.0))


__all__ = ["TextStats", "TextAccumulator", "sanitize_snippet"]
