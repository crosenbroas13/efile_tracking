from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern


CATEGORY_RULES: Dict[str, List[Rule]] = {
    "EMAIL_THREAD": [
        Rule("email_headers", re.compile(r"(?im)^(from|to|sent|subject|cc|bcc):")),
        Rule("original_message", re.compile(r"(?i)-{2,}\s*original message\s*-{2,}")),
        Rule("email_address", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)),
        Rule("timestamp", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}:\d{2}\s?(am|pm)?", re.IGNORECASE)),
    ],
    "LEGAL_PROCEEDING": [
        Rule("case_no", re.compile(r"(?i)\bcase\s+no\.?")),
        Rule("docket", re.compile(r"(?i)\bdocket\b")),
        Rule("party_roles", re.compile(r"(?i)\bplaintiff\b|\bdefendant\b")),
        Rule("court_terms", re.compile(r"(?i)\bcourt\b|\bhon\.\b")),
        Rule("motions", re.compile(r"(?i)\bmotion\b|\baffidavit\b|\bdeposition\b")),
        Rule("caption", re.compile(r"(?i)\bin the .* court\b")),
        Rule("versus", re.compile(r"\b v\. \b")),
    ],
    "LETTER_MEMO": [
        Rule("salutation", re.compile(r"(?im)^dear\s")),
        Rule("signoff", re.compile(r"(?im)^(sincerely|respectfully)\b")),
        Rule("memo_header", re.compile(r"(?im)^(to|from|date|subject|re):")),
    ],
    "FINANCIAL": [
        Rule("invoice", re.compile(r"(?i)\binvoice\b")),
        Rule("payment", re.compile(r"(?i)\bpayment\b|\bamount due\b")),
        Rule("account", re.compile(r"(?i)\baccount\b|\bwire\b")),
        Rule("currency", re.compile(r"\$\s?\d|\bUSD\b|\bEUR\b")),
    ],
    "CONTACT_LIST": [
        Rule("email_address", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)),
        Rule("phone_number", re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ],
    "FORM_TEMPLATE": [
        Rule("underscore_blank", re.compile(r"_{3,}")),
        Rule("checkbox", re.compile(r"\[\s*\]|\u2610|\u2611")),
        Rule("field_blank", re.compile(r"(?i)(name|date|signature|address|phone|email):\s*_{2,}")),
    ],
}


@dataclass
class ContentTypePrediction:
    content_type_pred: str
    content_type_confidence: float
    content_type_signals: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "content_type_pred": self.content_type_pred,
            "content_type_confidence": self.content_type_confidence,
            "content_type_signals": self.content_type_signals,
        }


class CategoryAccumulator:
    def __init__(self) -> None:
        self.rule_counts: Dict[str, Dict[str, int]] = {category: {} for category in CATEGORY_RULES}
        self.line_count = 0
        self.email_count = 0
        self.phone_count = 0
        self.underscore_runs = 0

    def update(self, text: str) -> None:
        if not text:
            return
        self.line_count += len(text.splitlines())
        for category, rules in CATEGORY_RULES.items():
            for rule in rules:
                hits = len(rule.pattern.findall(text))
                if hits:
                    self.rule_counts[category][rule.name] = self.rule_counts[category].get(rule.name, 0) + hits

        if "CONTACT_LIST" in CATEGORY_RULES:
            for rule in CATEGORY_RULES["CONTACT_LIST"]:
                if rule.name == "email_address":
                    self.email_count += len(rule.pattern.findall(text))
                if rule.name == "phone_number":
                    self.phone_count += len(rule.pattern.findall(text))
        if "FORM_TEMPLATE" in CATEGORY_RULES:
            for rule in CATEGORY_RULES["FORM_TEMPLATE"]:
                if rule.name == "underscore_blank":
                    self.underscore_runs += len(rule.pattern.findall(text))

    def finalize(self) -> ContentTypePrediction:
        scores = _score_categories(self.rule_counts, self.line_count, self.email_count, self.phone_count, self.underscore_runs)
        best_category, best_score = _pick_category(scores)
        confidence = _score_to_confidence(scores, best_score)
        signals = _format_signals(self.rule_counts, self.line_count, self.email_count, self.phone_count, self.underscore_runs)
        if best_score <= 0:
            return ContentTypePrediction("OTHER_TEXT", 0.0, signals)
        return ContentTypePrediction(best_category, confidence, signals)


def _score_categories(
    rule_counts: Dict[str, Dict[str, int]],
    line_count: int,
    email_count: int,
    phone_count: int,
    underscore_runs: int,
) -> Dict[str, float]:
    scores: Dict[str, float] = {category: 0.0 for category in CATEGORY_RULES}
    for category, hits in rule_counts.items():
        scores[category] += float(sum(hits.values()))

    if line_count:
        email_density = email_count / line_count
        phone_density = phone_count / line_count
        if email_density > 0.3 or phone_density > 0.3:
            scores["CONTACT_LIST"] += 3.0
        elif email_density > 0.15 or phone_density > 0.15:
            scores["CONTACT_LIST"] += 1.5

    if underscore_runs >= 5:
        scores["FORM_TEMPLATE"] += 2.0
    elif underscore_runs > 0:
        scores["FORM_TEMPLATE"] += 0.5
    return scores


def _pick_category(scores: Dict[str, float]) -> Tuple[str, float]:
    best_category = "OTHER_TEXT"
    best_score = 0.0
    for category, score in scores.items():
        if score > best_score:
            best_category = category
            best_score = score
    return best_category, best_score


def _score_to_confidence(scores: Dict[str, float], best_score: float) -> float:
    total = sum(scores.values())
    if best_score <= 0 or total <= 0:
        return 0.0
    return float(best_score / total)


def _format_signals(
    rule_counts: Dict[str, Dict[str, int]],
    line_count: int,
    email_count: int,
    phone_count: int,
    underscore_runs: int,
) -> str:
    payload = {
        "rule_hits": rule_counts,
        "stats": {
            "line_count": line_count,
            "email_address_count": email_count,
            "phone_number_count": phone_count,
            "underscore_runs": underscore_runs,
        },
    }
    return json.dumps(payload, sort_keys=True)


__all__ = ["ContentTypePrediction", "CategoryAccumulator"]
