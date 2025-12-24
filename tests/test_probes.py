from pathlib import Path

import pandas as pd

from src.probe_config import ProbeConfig
from src.probe_readiness import classify_document, stable_doc_id


def test_document_classification_thresholds():
    config = ProbeConfig(inventory_path=Path("dummy"), output_root=Path("out"))
    assert classify_document(0.95, config) == "Text-based"
    assert classify_document(0.05, config) == "Scanned"
    assert classify_document(0.5, config) == "Mixed"


def test_stable_doc_id_prefer_sha():
    row = pd.Series({"sha256": "abc", "rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row) == "abc"
    row_no_hash = pd.Series({"rel_path": "file.pdf", "size_bytes": 10, "modified_time": "2024"})
    assert stable_doc_id(row_no_hash) == "file.pdf|10|2024"
