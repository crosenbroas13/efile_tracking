from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

EMAIL_REGEX = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", re.IGNORECASE)
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
URL_REGEX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
DATE_REGEX = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b"
)

STRUCTURE_HINTS = {
    "email_headers": re.compile(r"\b(from:|subject:|to:)\b", re.IGNORECASE),
    "case_number": re.compile(r"\b(case\s+number|ticket\s+number)\b", re.IGNORECASE),
    "invoice": re.compile(r"\binvoice\b", re.IGNORECASE),
    "thank_you": re.compile(r"\bthank you for calling\b", re.IGNORECASE),
}


def extract_features(text: str, keywords: Dict[str, List[str]]) -> Dict[str, object]:
    normalized = text.lower()
    word_count = len(re.findall(r"\b\w+\b", normalized))

    keyword_counts: Dict[str, int] = {}
    for category, terms in keywords.items():
        count = sum(len(re.findall(rf"\b{re.escape(term.lower())}\b", normalized)) for term in terms)
        keyword_counts[category] = count

    keyword_total = Counter()
    for category, terms in keywords.items():
        for term in terms:
            term_count = len(re.findall(rf"\b{re.escape(term.lower())}\b", normalized))
            keyword_total[term] = term_count

    top_keywords = [term for term, count in keyword_total.most_common(5) if count > 0]

    structure_hits = [
        name for name, pattern in STRUCTURE_HINTS.items() if pattern.search(normalized)
    ]

    return {
        "word_count": word_count,
        "keyword_counts": keyword_counts,
        "top_keywords": top_keywords,
        "email_count": len(EMAIL_REGEX.findall(text)),
        "phone_count": len(PHONE_REGEX.findall(text)),
        "url_count": len(URL_REGEX.findall(text)),
        "date_like_count": len(DATE_REGEX.findall(text)),
        "structure_hints": structure_hits,
    }

