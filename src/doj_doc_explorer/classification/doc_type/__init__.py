"""Doc-type classification utilities."""

from .features import (  # noqa: F401
    DEFAULT_DPI,
    DEFAULT_PAGES_SAMPLED,
    DEFAULT_SEED,
    extract_doc_features,
)
from .model import (  # noqa: F401
    DOC_TYPE_LABELS,
    apply_doc_type_decision,
    load_doc_type_model,
    resolve_doc_type_model_path,
)

__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_PAGES_SAMPLED",
    "DEFAULT_SEED",
    "DOC_TYPE_LABELS",
    "apply_doc_type_decision",
    "extract_doc_features",
    "load_doc_type_model",
    "resolve_doc_type_model_path",
]
