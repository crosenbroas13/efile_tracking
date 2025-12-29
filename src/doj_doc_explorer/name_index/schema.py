from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_PUNCT_NORMALIZE = {
    "’": "'",
    "‘": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
}

_STOP_TOKENS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "united",
    "states",
    "state",
    "department",
    "court",
}


@dataclass(frozen=True)
class NormalizedName:
    canonical_key: str
    display_name: str
    variants: Tuple[str, ...]
    first: str
    last: str
    middle: Optional[str] = None
    suffix: Optional[str] = None


@dataclass(frozen=True)
class DocMetadata:
    doc_id: str
    rel_path: str
    page_count: int
    top_level_folder: str
    doj_url: Optional[str]
    doc_type_final: Optional[str]
    content_type: Optional[str]
    title: Optional[str]


@dataclass
class DocMention:
    doc_id: str
    rel_path: str
    page_count: int
    top_level_folder: str
    doj_url: Optional[str]
    doc_type_final: Optional[str]
    content_type: Optional[str]
    title: Optional[str]
    pages: Dict[int, int] = field(default_factory=dict)
    total_count: int = 0

    def add(self, page_num: int, count: int = 1) -> None:
        if page_num < 1:
            return
        self.pages[page_num] = self.pages.get(page_num, 0) + count
        self.total_count += count

    def to_dict(self) -> Dict[str, object]:
        page_list = [{"page_num": num, "count": count} for num, count in sorted(self.pages.items())]
        return {
            "doc_id": self.doc_id,
            "rel_path": self.rel_path,
            "page_count": self.page_count,
            "top_level_folder": self.top_level_folder,
            "doj_url": self.doj_url,
            "doc_type_final": self.doc_type_final,
            "content_type": self.content_type,
            "title": self.title,
            "pages": page_list,
            "total_count": self.total_count,
        }


@dataclass
class NameRecord:
    canonical_key: str
    display_name: str
    variants: List[str] = field(default_factory=list)
    docs: Dict[str, DocMention] = field(default_factory=dict)

    def total_count(self) -> int:
        return sum(doc.total_count for doc in self.docs.values())

    def to_dict(self) -> Dict[str, object]:
        docs_list = [doc.to_dict() for doc in sorted(self.docs.values(), key=lambda d: (d.rel_path, d.doc_id))]
        return {
            "canonical_key": self.canonical_key,
            "display_name": self.display_name,
            "variants": sorted(set(self.variants)),
            "total_count": self.total_count(),
            "docs": docs_list,
        }


class NameIndexAccumulator:
    def __init__(self) -> None:
        self._names: Dict[str, NameRecord] = {}

    def add(self, normalized: NormalizedName, doc: DocMetadata, page_num: int, count: int = 1) -> None:
        record = self._names.get(normalized.canonical_key)
        if record is None:
            record = NameRecord(
                canonical_key=normalized.canonical_key,
                display_name=normalized.display_name,
                variants=list(normalized.variants),
            )
            self._names[normalized.canonical_key] = record
        else:
            record.display_name = _choose_display_name(record.display_name, normalized.display_name)
            record.variants = sorted(set(record.variants).union(normalized.variants))

        doc_entry = record.docs.get(doc.doc_id)
        if doc_entry is None:
            doc_entry = DocMention(
                doc_id=doc.doc_id,
                rel_path=doc.rel_path,
                page_count=doc.page_count,
                top_level_folder=doc.top_level_folder,
                doj_url=doc.doj_url,
                doc_type_final=doc.doc_type_final,
                content_type=doc.content_type,
                title=doc.title,
            )
            record.docs[doc.doc_id] = doc_entry
        doc_entry.add(page_num, count)

    def to_records(self, min_total_count: int = 1) -> List[Dict[str, object]]:
        records = []
        for key in sorted(self._names.keys()):
            record = self._names[key]
            if record.total_count() < min_total_count:
                continue
            records.append(record.to_dict())
        return records

    def total_names(self) -> int:
        return len(self._names)


def normalize_person_name(
    *,
    first: str,
    last: str,
    middle: Optional[str] = None,
    suffix: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Optional[NormalizedName]:
    first_norm = _normalize_token(first)
    last_norm = _normalize_token(last)
    if not first_norm or not last_norm:
        return None
    if _is_stop_token(first_norm) or _is_stop_token(last_norm):
        return None
    if len(first_norm) < 2 or len(last_norm) < 2:
        return None

    middle_norm = _normalize_middle(middle) if middle else None
    suffix_norm = _normalize_suffix(suffix) if suffix else None
    canonical_key = f"{last_norm}|{first_norm}"
    display = display_name or _build_display_name(first, middle, last, suffix)
    variants = _build_variants(first_norm, last_norm, middle_norm)
    return NormalizedName(
        canonical_key=canonical_key,
        display_name=display,
        variants=variants,
        first=first_norm,
        last=last_norm,
        middle=middle_norm,
        suffix=suffix_norm,
    )


def build_public_records(records: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    public_records: List[Dict[str, object]] = []
    for record in records:
        docs = record.get("docs", [])
        public_docs = []
        for doc in docs:
            public_docs.append(
                {
                    "title": doc.get("title"),
                    "doc_id": doc.get("doc_id"),
                    "rel_path": doc.get("rel_path"),
                    "doj_url": doc.get("doj_url"),
                    "doc_type_final": doc.get("doc_type_final"),
                    "content_type": doc.get("content_type"),
                    "pages": doc.get("pages", []),
                    "total_count": doc.get("total_count", 0),
                }
            )
        public_records.append(
            {
                "canonical_key": record.get("canonical_key"),
                "display_name": record.get("display_name"),
                "docs": public_docs,
            }
        )
    return public_records


def _normalize_token(token: str) -> str:
    if token is None:
        return ""
    cleaned = str(token)
    for src, target in _PUNCT_NORMALIZE.items():
        cleaned = cleaned.replace(src, target)
    cleaned = re.sub(r"[^A-Za-z'-]", "", cleaned)
    return cleaned.lower()


def _normalize_middle(middle: str) -> Optional[str]:
    token = _normalize_token(middle)
    if not token:
        return None
    if len(token) > 1:
        token = token[0]
    return token


def _normalize_suffix(suffix: str) -> Optional[str]:
    token = _normalize_token(suffix)
    return token or None


def _build_display_name(first: str, middle: Optional[str], last: str, suffix: Optional[str]) -> str:
    parts = [first]
    if middle:
        middle_clean = middle.rstrip(".")
        if middle_clean:
            parts.append(f"{middle_clean}.")
    parts.append(last)
    if suffix:
        parts.append(suffix.rstrip("."))
    return " ".join(parts).strip()


def _build_variants(first: str, last: str, middle: Optional[str]) -> Tuple[str, ...]:
    base_first_last = f"{first} {last}".strip()
    base_last_first = f"{last} {first}".strip()
    base_last_comma = f"{last}, {first}".strip()
    variants = {base_first_last, base_last_first, base_last_comma}
    if middle:
        variants.add(f"{first} {middle} {last}".strip())
    return tuple(sorted(variants))


def _choose_display_name(existing: str, candidate: str) -> str:
    if not existing:
        return candidate
    if existing.isupper() and not candidate.isupper():
        return candidate
    return existing


def _is_stop_token(token: str) -> bool:
    return token.lower() in _STOP_TOKENS


def is_all_caps_heading(line: str) -> bool:
    if not line:
        return False
    tokens = [t for t in re.split(r"\s+", line.strip()) if t]
    if len(tokens) <= 2:
        return False
    for token in tokens:
        cleaned = re.sub(r"[^A-Za-z]", "", token)
        if cleaned and not cleaned.isupper():
            return False
    return True


def tokens_from_line(line: str) -> Iterable[str]:
    return [token for token in re.split(r"\s+", line.strip()) if token]


__all__ = [
    "NormalizedName",
    "DocMetadata",
    "DocMention",
    "NameRecord",
    "NameIndexAccumulator",
    "normalize_person_name",
    "build_public_records",
    "is_all_caps_heading",
]
