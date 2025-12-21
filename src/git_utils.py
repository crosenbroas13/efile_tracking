from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def current_git_commit(repo_path: Path | str = ".") -> Optional[str]:
    repo = Path(repo_path)
    if not (repo / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


__all__ = ["current_git_commit"]
