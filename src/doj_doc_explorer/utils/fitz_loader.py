"""Helpers for safely importing PyMuPDF (fitz) with clear guidance."""

from __future__ import annotations

from typing import Optional


_PYMUPDF_REQUIRED_ATTRS = ("open", "Matrix", "csGRAY")


def _error_message() -> str:
    return (
        "PyMuPDF is required for PDF rendering features, but the installed "
        "'fitz' package is not PyMuPDF. Uninstall the wrong package and "
        "install PyMuPDF instead:\n\n"
        "  pip uninstall fitz\n"
        "  pip install PyMuPDF\n"
    )


def load_fitz(*, strict: bool = True):
    """Return the PyMuPDF module or None, with a safe, guided error on mismatch."""
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive for bad installs
        if strict:
            raise RuntimeError(_error_message()) from exc
        return None

    if not all(hasattr(fitz, attr) for attr in _PYMUPDF_REQUIRED_ATTRS):
        if strict:
            raise RuntimeError(_error_message())
        return None

    return fitz


def load_fitz_optional() -> Optional[object]:
    """Return PyMuPDF or None without raising."""
    return load_fitz(strict=False)
