from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from src.probe_readiness import stable_doc_id

from ..utils.io import ensure_dir, read_json, write_json
from ..utils.paths import normalize_rel_path

LOGGER = logging.getLogger(__name__)

LABELS_FILENAME = "pdf_type_labels.csv"
LABEL_VALUES = {"TEXT_PDF", "IMAGE_OF_TEXT_PDF", "IMAGE_PDF", "MIXED_PDF"}
LABELING_REQUIRED_COLUMNS = [
    "rel_path",
    "label_raw",
    "label_norm",
    "labeled_at",
]
LABELING_OPTIONAL_COLUMNS = [
    "notes",
    "source_inventory_run",
    "source_probe_run",
    "sha256_at_label_time",
    "doc_id_at_label_time",
    "labeling_version",
]


@dataclass
class LabelMatchResult:
    matched: pd.DataFrame
    orphaned: pd.DataFrame
    unmatched_inventory: pd.DataFrame


def labels_path(outputs_root: Path) -> Path:
    return ensure_dir(Path(outputs_root) / "labels") / LABELS_FILENAME


def load_inventory(inventory_path: Path) -> pd.DataFrame:
    if not inventory_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(inventory_path)
    if "rel_path" in df.columns:
        df["rel_path"] = df["rel_path"].astype(str).map(normalize_rel_path)
    if "top_level_folder" not in df.columns:
        df["top_level_folder"] = df["rel_path"].fillna("").map(_top_level_folder_from_rel_path)
    if "extension" in df.columns:
        df["extension"] = df["extension"].fillna("").str.lower()
    return df


def load_labels(labels_csv: Path, inventory_df: pd.DataFrame, *, write_back: bool = True) -> pd.DataFrame:
    if not labels_csv.exists():
        return _empty_labels()
    labels_df = pd.read_csv(labels_csv)
    upgrade_needed = _missing_required_columns(labels_df)
    labels_df = _ensure_label_columns(labels_df)
    if "rel_path" in labels_df.columns:
        labels_df["rel_path"] = labels_df["rel_path"].astype(str).map(normalize_rel_path)
    labels_df["label_raw"] = labels_df["label_raw"].fillna("").astype(str)
    labels_df["label_norm"] = labels_df["label_raw"].map(normalize_label_value)
    if "label" in labels_df.columns:
        labels_df["label"] = labels_df["label"].fillna(labels_df["label_raw"]).astype(str)

    updated_df, recovered = _recover_rel_paths(labels_df, inventory_df)
    if recovered:
        for message in recovered:
            LOGGER.info(message)
        if write_back:
            write_labels(updated_df, labels_csv)
    if upgrade_needed and write_back:
        write_labels(updated_df, labels_csv)
    return updated_df


def write_labels(labels_df: pd.DataFrame, labels_csv: Path) -> Path:
    labels_df = _ensure_label_columns(labels_df)
    labels_df.to_csv(labels_csv, index=False)
    return labels_csv


def match_labels_to_inventory(inventory_df: pd.DataFrame, labels_df: pd.DataFrame) -> LabelMatchResult:
    matched: List[Dict[str, object]] = []
    orphaned: List[Dict[str, object]] = []

    inventory_df = inventory_df.copy()
    labels_df = labels_df.copy()
    inventory_df["rel_path"] = inventory_df["rel_path"].astype(str).map(normalize_rel_path)
    labels_df["rel_path"] = labels_df["rel_path"].astype(str).map(normalize_rel_path)

    needs_doc_id_validation = labels_df["doc_id_at_label_time"].fillna("").astype(str).str.strip().any()
    needs_sha_validation = labels_df["sha256_at_label_time"].fillna("").astype(str).str.strip().any()

    if needs_doc_id_validation and "doc_id_current" not in inventory_df.columns:
        inventory_df["doc_id_current"] = inventory_df.apply(_compute_doc_id, axis=1)

    rel_path_groups = inventory_df.groupby("rel_path", dropna=False)
    for _, label_row in labels_df.iterrows():
        rel_path = str(label_row.get("rel_path", "")).strip()
        if not rel_path:
            orphaned.append({**label_row.to_dict(), "orphaned_label": True})
            continue
        matches = rel_path_groups.get_group(rel_path) if rel_path in rel_path_groups.groups else pd.DataFrame()
        if matches.empty:
            orphaned.append({**label_row.to_dict(), "orphaned_label": True})
            continue
        if len(matches) > 1:
            rel_top = _top_level_folder_from_rel_path(rel_path)
            filtered = matches[matches["top_level_folder"] == rel_top]
            if len(filtered) == 1:
                matches = filtered
            else:
                LOGGER.warning("Ambiguous label match for rel_path=%s; skipping.", rel_path)
                orphaned.append({**label_row.to_dict(), "orphaned_label": True})
                continue
        inventory_row = matches.iloc[0].to_dict()
        _validate_label_row(label_row, inventory_row, needs_doc_id_validation, needs_sha_validation)
        matched.append({**inventory_row, **label_row.to_dict(), "orphaned_label": False})

    matched_df = pd.DataFrame(matched)
    orphaned_df = pd.DataFrame(orphaned)

    labeled_rel_paths = set(matched_df["rel_path"].astype(str)) if not matched_df.empty else set()
    if labeled_rel_paths:
        unlabeled_mask = ~inventory_df["rel_path"].astype(str).isin(labeled_rel_paths)
        unmatched_inventory = inventory_df[unlabeled_mask].copy()
    else:
        unmatched_inventory = inventory_df.copy()
    return LabelMatchResult(matched=matched_df, orphaned=orphaned_df, unmatched_inventory=unmatched_inventory)


def reconcile_labels(
    *,
    inventory_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    outputs_root: Path,
    inventory_id: str,
    match_result: Optional[LabelMatchResult] = None,
) -> Dict[str, int]:
    result = match_result or match_labels_to_inventory(inventory_df, labels_df)
    counts = {
        "labels_matched": int(len(result.matched)),
        "labels_orphaned": int(len(result.orphaned)),
        "docs_unlabeled": int(len(result.unmatched_inventory)),
    }
    LOGGER.info(
        "Label reconciliation: matched=%s orphaned=%s unlabeled=%s",
        counts["labels_matched"],
        counts["labels_orphaned"],
        counts["docs_unlabeled"],
    )
    print(
        "Label reconciliation:",
        f"matched={counts['labels_matched']}",
        f"orphaned={counts['labels_orphaned']}",
        f"unlabeled={counts['docs_unlabeled']}",
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_id": inventory_id,
        **counts,
    }
    report_path = ensure_dir(Path(outputs_root) / "labels") / f"label_reconciliation_{timestamp}.json"
    write_json(report_path, report)
    return counts


def _ensure_label_columns(labels_df: pd.DataFrame) -> pd.DataFrame:
    labels_df = labels_df.copy()
    if "rel_path" not in labels_df.columns:
        labels_df["rel_path"] = ""
    if "label_raw" not in labels_df.columns:
        if "label" in labels_df.columns:
            labels_df["label_raw"] = labels_df["label"]
        elif "label_norm" in labels_df.columns:
            labels_df["label_raw"] = labels_df["label_norm"]
        else:
            labels_df["label_raw"] = ""
    if "label_norm" not in labels_df.columns:
        labels_df["label_norm"] = pd.NA
    if "labeled_at" not in labels_df.columns:
        labels_df["labeled_at"] = ""
    for column in LABELING_OPTIONAL_COLUMNS:
        if column not in labels_df.columns:
            labels_df[column] = ""
    if "label" in labels_df.columns:
        labels_df["label"] = labels_df["label"].fillna(labels_df["label_raw"])
    ordered = [col for col in LABELING_REQUIRED_COLUMNS + LABELING_OPTIONAL_COLUMNS if col in labels_df.columns]
    remaining = [col for col in labels_df.columns if col not in ordered]
    labels_df = labels_df[ordered + remaining]
    return labels_df


def _empty_labels() -> pd.DataFrame:
    return pd.DataFrame(columns=LABELING_REQUIRED_COLUMNS + LABELING_OPTIONAL_COLUMNS)


def _recover_rel_paths(labels_df: pd.DataFrame, inventory_df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    recovered_messages: List[str] = []
    if labels_df.empty or inventory_df.empty:
        return labels_df, recovered_messages
    if "rel_path" not in labels_df.columns:
        labels_df["rel_path"] = ""

    missing_mask = labels_df["rel_path"].fillna("").astype(str).str.strip() == ""
    if not missing_mask.any():
        return labels_df, recovered_messages

    inventory_df = inventory_df.copy()
    inventory_df["rel_path"] = inventory_df["rel_path"].astype(str).map(normalize_rel_path)

    doc_id_map: Dict[str, List[str]] = {}
    sha_map: Dict[str, List[str]] = {}

    if "doc_id_at_label_time" in labels_df.columns or "doc_id" in labels_df.columns:
        inventory_df["doc_id_current"] = inventory_df.apply(_compute_doc_id, axis=1)
        for rel_path, doc_id in zip(inventory_df["rel_path"], inventory_df["doc_id_current"], strict=False):
            doc_id_map.setdefault(str(doc_id), []).append(str(rel_path))

    hash_col = "hash_value" if "hash_value" in inventory_df.columns else ("sha256" if "sha256" in inventory_df.columns else None)
    if hash_col and ("sha256_at_label_time" in labels_df.columns or "sha256" in labels_df.columns):
        for rel_path, digest in zip(inventory_df["rel_path"], inventory_df[hash_col], strict=False):
            if pd.notna(digest) and str(digest).strip():
                sha_map.setdefault(str(digest), []).append(str(rel_path))

    for idx in labels_df[missing_mask].index:
        row = labels_df.loc[idx]
        doc_id_value = str(row.get("doc_id_at_label_time") or row.get("doc_id") or "").strip()
        sha_value = str(row.get("sha256_at_label_time") or row.get("sha256") or "").strip()
        rel_path = ""
        if doc_id_value and doc_id_value in doc_id_map:
            rel_path = _choose_rel_path(doc_id_map[doc_id_value])
        elif sha_value and sha_value in sha_map:
            rel_path = _choose_rel_path(sha_map[sha_value])
        if rel_path:
            labels_df.at[idx, "rel_path"] = rel_path
            recovered_messages.append(f"Recovered rel_path for label row {idx}: {rel_path}")
        else:
            recovered_messages.append(f"Could not recover rel_path for label row {idx}")

    labels_df["rel_path"] = labels_df["rel_path"].astype(str).map(normalize_rel_path)
    return labels_df, recovered_messages


def _choose_rel_path(paths: Iterable[str]) -> str:
    candidates = list({normalize_rel_path(p) for p in paths if p})
    if len(candidates) == 1:
        return candidates[0]
    return ""


def _validate_label_row(
    label_row: pd.Series,
    inventory_row: Dict[str, object],
    needs_doc_id_validation: bool,
    needs_sha_validation: bool,
) -> None:
    rel_path = inventory_row.get("rel_path", "")
    if needs_doc_id_validation:
        doc_id_label = str(label_row.get("doc_id_at_label_time") or "").strip()
        if doc_id_label:
            doc_id_current = inventory_row.get("doc_id_current")
            if doc_id_current and str(doc_id_current) != doc_id_label:
                LOGGER.warning("doc_id mismatch for %s: label=%s current=%s", rel_path, doc_id_label, doc_id_current)
    if needs_sha_validation:
        sha_label = str(label_row.get("sha256_at_label_time") or "").strip()
        if sha_label:
            sha_current = inventory_row.get("hash_value") or inventory_row.get("sha256")
            if sha_current and str(sha_current) != sha_label:
                LOGGER.warning("sha256 mismatch for %s: label=%s current=%s", rel_path, sha_label, sha_current)


def _top_level_folder_from_rel_path(rel_path: str) -> str:
    if not rel_path:
        return ""
    parts = normalize_rel_path(rel_path).split("/")
    return parts[0] if parts else ""


def _compute_doc_id(row: pd.Series) -> str:
    series = pd.Series(
        {
            "sha256": row.get("sha256"),
            "rel_path": row.get("rel_path"),
            "size_bytes": row.get("size_bytes"),
            "modified_time": row.get("modified_time"),
        }
    )
    return stable_doc_id(series)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def inventory_identity(inventory_path: Path) -> str:
    run_log = read_json(inventory_path.with_name("run_log.json"))
    if run_log.get("inventory_run_id"):
        return str(run_log["inventory_run_id"])
    if inventory_path.name == "inventory.csv" and inventory_path.parent.parent.name == "inventory":
        return inventory_path.parent.name
    if inventory_path.exists():
        return f"hash:{_hash_file(inventory_path)}"
    return str(inventory_path)


def normalize_labels_for_save(labels_df: pd.DataFrame) -> pd.DataFrame:
    labels_df = labels_df.copy()
    labels_df["rel_path"] = labels_df["rel_path"].astype(str).map(normalize_rel_path)
    labels_df["label_raw"] = labels_df["label_raw"].fillna("").astype(str)
    labels_df["label_norm"] = labels_df["label_raw"].map(normalize_label_value)
    if "label" in labels_df.columns:
        labels_df["label"] = labels_df["label"].fillna(labels_df["label_raw"]).astype(str)
    return labels_df


def filter_pdf_inventory(inventory_df: pd.DataFrame) -> pd.DataFrame:
    if "extension" in inventory_df.columns:
        return inventory_df[inventory_df["extension"] == "pdf"].copy()
    return inventory_df.copy()


def _missing_required_columns(labels_df: pd.DataFrame) -> bool:
    return any(column not in labels_df.columns for column in LABELING_REQUIRED_COLUMNS)


def normalize_label_value(value: object) -> Optional[str]:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized == "IMAGE_PDF":
        return "IMAGE_PDF"
    if normalized == "TEXT_PDF":
        return "IMAGE_OF_TEXT_PDF"
    if normalized == "MIXED_PDF":
        return "MIXED_PDF"
    if normalized == "IMAGE_OF_TEXT_PDF":
        return "IMAGE_OF_TEXT_PDF"
    return None


__all__ = [
    "LABELS_FILENAME",
    "LABEL_VALUES",
    "LABELING_REQUIRED_COLUMNS",
    "LABELING_OPTIONAL_COLUMNS",
    "LabelMatchResult",
    "filter_pdf_inventory",
    "inventory_identity",
    "labels_path",
    "load_inventory",
    "load_labels",
    "match_labels_to_inventory",
    "normalize_label_value",
    "normalize_labels_for_save",
    "reconcile_labels",
    "write_labels",
]
