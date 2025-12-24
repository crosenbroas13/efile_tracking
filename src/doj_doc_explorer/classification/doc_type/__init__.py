"""Doc-type classification utilities."""

from .constants import DEFAULT_DPI, DEFAULT_PAGES_SAMPLED, DEFAULT_SEED  # noqa: F401
from .decision import apply_doc_type_decision  # noqa: F401
from .registry import resolve_doc_type_model_path  # noqa: F401
from .model import (  # noqa: F401
    DOC_TYPE_LABELS,
    load_doc_type_model,
)

__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_PAGES_SAMPLED",
    "DEFAULT_SEED",
    "DOC_TYPE_LABELS",
    "apply_doc_type_decision",
    "load_doc_type_model",
    "resolve_doc_type_model_path",
]
