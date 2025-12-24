from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...utils.io import read_json

MODEL_POINTER = "LATEST.json"


def resolve_doc_type_model_path(model_ref: str, outputs_root: Path) -> Optional[Path]:
    if not model_ref or model_ref == "LATEST":
        pointer = read_json(outputs_root / "models" / "doc_type" / MODEL_POINTER)
        run_dir = pointer.get("run_dir")
        if run_dir:
            candidate = outputs_root / run_dir / "model.joblib"
            if candidate.exists():
                return candidate
        return None
    candidate = Path(model_ref)
    if candidate.exists():
        if candidate.is_dir():
            model_path = candidate / "model.joblib"
            return model_path if model_path.exists() else None
        return candidate
    run_dir = outputs_root / "models" / "doc_type" / model_ref
    model_path = run_dir / "model.joblib"
    if model_path.exists():
        return model_path
    return None


__all__ = ["MODEL_POINTER", "resolve_doc_type_model_path"]
