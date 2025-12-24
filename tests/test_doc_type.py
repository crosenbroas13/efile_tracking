from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz
import numpy as np
import pandas as pd

from src.doj_doc_explorer.classification.doc_type.features import projection_variance
from src.doj_doc_explorer.classification.doc_type.model import (
    apply_doc_type_decision,
    load_doc_type_model,
    predict_doc_types,
    train_doc_type_model,
)
from src.doj_doc_explorer.pdf_type.labels import match_labels_to_inventory, normalize_label_value
from src.doj_doc_explorer.utils.paths import normalize_rel_path


def _write_simple_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def _build_inventory_csv(root: Path, pdf_paths: list[Path]) -> Path:
    rows = []
    for pdf_path in pdf_paths:
        rel_path = pdf_path.relative_to(root).as_posix()
        rows.append(
            {
                "rel_path": rel_path,
                "abs_path": str(pdf_path),
                "extension": "pdf",
                "size_bytes": pdf_path.stat().st_size,
                "modified_time": datetime.utcfromtimestamp(pdf_path.stat().st_mtime).isoformat(),
                "top_level_folder": rel_path.split("/")[0],
            }
        )
    df = pd.DataFrame(rows)
    inventory_path = root / "inventory.csv"
    df.to_csv(inventory_path, index=False)
    return inventory_path


def _build_labels_csv(root: Path, rel_paths: list[str], labels: list[str]) -> Path:
    rows = []
    now = datetime.utcnow().isoformat()
    for rel_path, label in zip(rel_paths, labels, strict=False):
        rows.append(
            {
                "rel_path": rel_path,
                "label_raw": label,
                "label_norm": normalize_label_value(label),
                "labeled_at": now,
            }
        )
    labels_path = root / "labels.csv"
    pd.DataFrame(rows).to_csv(labels_path, index=False)
    return labels_path


def test_label_migration_normalizes_text_pdf():
    assert normalize_label_value("TEXT_PDF") == "IMAGE_OF_TEXT_PDF"
    assert normalize_label_value("IMAGE_PDF") == "IMAGE_PDF"


def test_rel_path_normalization_match():
    inventory_df = pd.DataFrame(
        {
            "rel_path": ["Folder/Sub/file.pdf"],
            "extension": ["pdf"],
            "top_level_folder": ["Folder"],
        }
    )
    labels_df = pd.DataFrame(
        {
            "rel_path": ["Folder\\Sub\\file.pdf"],
            "label_raw": ["IMAGE_PDF"],
            "label_norm": ["IMAGE_PDF"],
            "labeled_at": ["2024-01-01"],
            "doc_id_at_label_time": [""],
            "sha256_at_label_time": [""],
        }
    )
    result = match_labels_to_inventory(inventory_df, labels_df)
    assert not result.matched.empty
    assert normalize_rel_path(result.matched.iloc[0]["rel_path"]) == "folder/sub/file.pdf"


def test_projection_variance_text_like_higher_than_noise():
    text_like = np.zeros((100, 200), dtype=np.uint8)
    text_like[10::10, :] = 1
    noise = np.random.RandomState(42).randint(0, 2, size=(100, 200)).astype(np.uint8)

    text_var_row, _ = projection_variance(text_like)
    noise_var_row, _ = projection_variance(noise)
    assert text_var_row > noise_var_row


def test_train_save_load_predict_pipeline(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    pdf_paths = []
    labels = []
    for idx in range(6):
        pdf_path = data_root / f"doc_{idx}.pdf"
        _write_simple_pdf(pdf_path, f"Doc {idx}")
        pdf_paths.append(pdf_path)
        labels.append("IMAGE_PDF" if idx % 2 == 0 else "IMAGE_OF_TEXT_PDF")

    inventory_path = _build_inventory_csv(data_root, pdf_paths)
    labels_path = _build_labels_csv(tmp_path, [p.relative_to(data_root).as_posix() for p in pdf_paths], labels)

    outputs_root = tmp_path / "outputs"
    outputs_root.mkdir()

    artifacts, _ = train_doc_type_model(
        inventory_path=inventory_path,
        probe_ref="NONE",
        labels_csv=labels_path,
        outputs_root=outputs_root,
        pages_sampled=1,
        dpi=72,
        seed=123,
        eval_split=0.33,
    )
    loaded = load_doc_type_model("LATEST", outputs_root)
    assert loaded is not None

    pdfs_df = pd.read_csv(inventory_path)
    predictions = predict_doc_types(
        pdfs_df=pdfs_df,
        probe_docs=None,
        model_artifacts=loaded,
        pages_sampled=1,
        dpi=72,
        seed=123,
        reason_features=False,
    )
    assert len(predictions) == len(pdf_paths)
    assert "predicted_label" in predictions.columns
    assert "proba_IMAGE_PDF" in predictions.columns


def test_probe_decision_rule_priority():
    docs_df = pd.DataFrame(
        {
            "doc_type_truth": ["IMAGE_PDF", "", ""],
            "doc_type_model_pred": ["MIXED_PDF", "IMAGE_PDF", "IMAGE_PDF"],
            "model_confidence": [0.2, 0.8, 0.5],
            "doc_type_heuristic": ["TEXT_PDF", "TEXT_PDF", "IMAGE_OF_TEXT_PDF"],
        }
    )
    result = apply_doc_type_decision(docs_df, min_confidence=0.7)
    assert result.loc[0, "doc_type_final"] == "IMAGE_PDF"
    assert result.loc[0, "doc_type_source"] == "TRUTH"
    assert result.loc[1, "doc_type_final"] == "IMAGE_PDF"
    assert result.loc[1, "doc_type_source"] == "MODEL"
    assert result.loc[2, "doc_type_final"] == "IMAGE_OF_TEXT_PDF"
    assert result.loc[2, "doc_type_source"] == "HEURISTIC"
