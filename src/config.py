from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import fnmatch

DEFAULT_IGNORE = ["*.DS_Store", "Thumbs.db", "~$*"]


def normalize_patterns(patterns: Optional[List[str]]) -> List[str]:
    return [p for p in (patterns or []) if p]


def should_ignore(path: Path, root: Path, patterns: List[str]) -> bool:
    if not patterns:
        return False
    rel_path = path.relative_to(root)
    rel_parts = rel_path.as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel_parts, pattern):
            return True
    return False


@dataclass
class InventoryConfig:
    root: Path
    out_dir: Path
    hash_algorithm: str = "sha256"
    sample_bytes: int = 0
    ignore_patterns: List[str] = field(default_factory=list)
    follow_symlinks: bool = False
    max_files: Optional[int] = None

    def effective_ignore(self) -> List[str]:
        return DEFAULT_IGNORE + normalize_patterns(self.ignore_patterns)

    def hash_enabled(self) -> bool:
        return self.hash_algorithm.lower() != "none"
