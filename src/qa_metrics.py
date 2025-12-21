"""QA metrics and helpers derived from inventory outputs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB
COMMON_EXTENSIONS = {
    "pdf",
    "txt",
    "csv",
    "tsv",
    "log",
    "md",
    "json",
    "xml",
    "html",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "tif",
    "tiff",
    "bmp",
    "heic",
    "mp3",
    "wav",
    "mp4",
    "mov",
    "avi",
    "zip",
    "gz",
    "tar",
}


def human_readable_bytes(num_bytes: float | int) -> str:
    if pd.isna(num_bytes):
        return "unknown"
    num = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def safe_parse_datetime(value) -> Optional[datetime]:
    if value in (None, "", pd.NA):
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Series):
        ts = ts.iloc[0]
    return ts.to_pydatetime()


def categorize_file(extension: Optional[str], mime: Optional[str]) -> str:
    ext = (extension or "").lower().strip(".")
    mime = (mime or "").lower()

    if ext == "pdf" or mime.startswith("application/pdf"):
        return "pdf"
    if ext in {"txt", "log", "md"} or (mime.startswith("text/") and "csv" not in mime and "tsv" not in mime):
        return "text"
    if ext in {"csv", "tsv"} or "csv" in mime or "tsv" in mime:
        return "csv"
    if ext in {"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "heic"} or mime.startswith("image/"):
        return "image"
    return "other"


def count_file_categories(df: pd.DataFrame) -> Dict[str, int]:
    categories = df.apply(lambda r: categorize_file(r.get("extension"), r.get("detected_mime")), axis=1)
    return categories.value_counts().to_dict()


def compute_executive_summary(df: pd.DataFrame, errors_count: int = 0) -> Dict:
    total_files = len(df)
    total_bytes = df.get("size_bytes").sum() if "size_bytes" in df else None
    total_size_gb = float(total_bytes) / (1024 ** 3) if total_bytes is not None else 0.0
    categories = count_file_categories(df)
    top_level_count = df["top_level_folder"].nunique() if "top_level_folder" in df else 0

    return {
        "total_files": int(total_files),
        "total_size_gb": total_size_gb,
        "file_type_counts": categories,
        "top_level_folders": int(top_level_count),
        "errors_count": errors_count,
    }


def rollup_by_top_level(df: pd.DataFrame) -> pd.DataFrame:
    if "top_level_folder" not in df or df.empty:
        return pd.DataFrame(columns=["top_level_folder", "files", "total_bytes", "percent_of_total"])

    grouped = df.groupby("top_level_folder").agg(files=("rel_path", "count"), total_bytes=("size_bytes", "sum"))
    total_bytes = grouped["total_bytes"].sum() or 1
    grouped["percent_of_total"] = (grouped["total_bytes"] / total_bytes) * 100
    return grouped.reset_index().sort_values("total_bytes", ascending=False)


def deepest_paths(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    if "rel_path" not in df:
        return pd.DataFrame(columns=["folder", "files", "depth"])

    parents = df["rel_path"].apply(lambda p: str(Path(p).parent))
    grouped = parents.groupby(parents).agg(files="count")
    result = grouped.reset_index()
    result.columns = ["folder", "files"]
    result["depth"] = result["folder"].apply(lambda p: len(Path(p).parts))
    return result.sort_values(["depth", "files"], ascending=[False, False]).head(n)


def counts_by_extension_and_mime(df: pd.DataFrame) -> pd.DataFrame:
    ext_col = df.get("extension", pd.Series([None] * len(df)))
    mime_col = df.get("detected_mime", pd.Series([None] * len(df)))
    grouped = df.assign(extension=ext_col, detected_mime=mime_col).groupby(["extension", "detected_mime"]).size()
    return grouped.reset_index(name="count").sort_values("count", ascending=False)


def size_histogram(df: pd.DataFrame, bins: Sequence[int] | None = None) -> pd.Series:
    if "size_bytes" not in df or df.empty:
        return pd.Series(dtype="int64")

    sizes = df["size_bytes"].dropna().astype(float)
    if bins is None:
        bins = [0, 1024, 10_000, 100_000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000, float("inf")]
    labels = [
        "<1 KB",
        "1-10 KB",
        "10-100 KB",
        "0.1-1 MB",
        "1-10 MB",
        "10-100 MB",
        "100 MB - 1 GB",
        ">1 GB",
    ]
    binned = pd.cut(sizes, bins=bins, labels=labels, right=False, include_lowest=True)
    return binned.value_counts().sort_index()


def largest_files(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    if "size_bytes" not in df:
        return pd.DataFrame(columns=df.columns)
    cols = [c for c in ["rel_path", "size_bytes", "extension", "detected_mime", "top_level_folder"] if c in df.columns]
    return df.sort_values("size_bytes", ascending=False).head(top_n)[cols]


def find_duplicate_groups(df: pd.DataFrame, *, use_hash: bool = True, hash_column: str = "hash_value") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["hash", "count", "total_bytes", "example_paths"])

    if use_hash:
        if hash_column not in df:
            return pd.DataFrame(columns=["hash", "count", "total_bytes", "example_paths"])
        candidates = df[df[hash_column].notna() & (df[hash_column] != "")]
        group_field = hash_column
    else:
        group_field = "rel_path"
        candidates = df[df[group_field].notna()]

    grouped = candidates.groupby(group_field)
    rows = []
    for key, group in grouped:
        if len(group) < 2:
            continue
        total_bytes = group["size_bytes"].sum() if "size_bytes" in group else None
        example_paths = list(group.get("rel_path", [])[:3])
        rows.append({"hash": key, "count": len(group), "total_bytes": total_bytes, "example_paths": example_paths})

    result = pd.DataFrame(rows, columns=["hash", "count", "total_bytes", "example_paths"])
    if "total_bytes" in result:
        result = result.sort_values(["count", "total_bytes"], ascending=[False, False])
    return result


@dataclass
class IssueConfig:
    large_file_threshold: int = LARGE_FILE_THRESHOLD_BYTES


@dataclass
class IssueRecord:
    rel_path: str
    issues: List[str]
    size_bytes: Optional[float]
    extension: Optional[str]
    detected_mime: Optional[str]
    modified_time: Optional[str]


def detect_potential_issues(df: pd.DataFrame, config: IssueConfig | None = None) -> pd.DataFrame:
    if config is None:
        config = IssueConfig()

    rows: List[Dict] = []
    now = datetime.now(timezone.utc)
    known_ext = COMMON_EXTENSIONS

    for _, row in df.iterrows():
        flagged: List[str] = []
        size = row.get("size_bytes")
        mime = (row.get("detected_mime") or "").strip().lower()
        ext = (row.get("extension") or "").strip().lower().strip(".")
        rel_path = row.get("rel_path") or "(unknown path)"

        if pd.notna(size) and float(size) == 0:
            flagged.append("zero_size")
        if not mime or mime in {"unknown", "application/octet-stream"}:
            flagged.append("missing_mime")
        if pd.notna(size) and float(size) >= config.large_file_threshold:
            flagged.append("very_large")
        if not ext or ext not in known_ext:
            flagged.append("uncommon_extension")
        mod_time = row.get("modified_time")
        parsed_time = safe_parse_datetime(mod_time)
        if parsed_time and parsed_time > now:
            flagged.append("future_modified_time")

        if flagged:
            rows.append(
                {
                    "rel_path": rel_path,
                    "issues": ", ".join(flagged),
                    "size_bytes": size,
                    "extension": ext,
                    "detected_mime": mime or None,
                    "modified_time": mod_time,
                }
            )

    return pd.DataFrame(rows)
