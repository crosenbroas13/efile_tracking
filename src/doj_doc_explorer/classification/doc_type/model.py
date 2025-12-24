from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.probe_readiness import list_pdfs

from ...config import new_run_id
from ...pdf_type.labels import (
    filter_pdf_inventory,
    inventory_identity,
    load_inventory,
    load_labels,
    match_labels_to_inventory,
    normalize_label_value,
)
from ...utils.git import current_git_commit
from ...utils.io import ensure_dir, latest_probe, load_table, read_json, write_json
from ...utils.paths import normalize_rel_path
from .constants import DEFAULT_DPI, DEFAULT_PAGES_SAMPLED, DEFAULT_SEED
from .decision import apply_doc_type_decision
from .features import extract_doc_features
from .registry import MODEL_POINTER, resolve_doc_type_model_path

DOC_TYPE_LABELS = ["TEXT_PDF", "IMAGE_OF_TEXT_PDF", "IMAGE_PDF", "MIXED_PDF"]


@dataclass(frozen=True)
class ModelArtifacts:
    model: Pipeline
    model_dir: Path
    model_id: str
    model_card: Dict[str, object]


def train_doc_type_model(
    *,
    inventory_path: Path,
    probe_ref: str,
    labels_csv: Path,
    outputs_root: Path,
    pages_sampled: int = DEFAULT_PAGES_SAMPLED,
    dpi: int = DEFAULT_DPI,
    seed: int = DEFAULT_SEED,
    eval_split: float = 0.2,
) -> Tuple[ModelArtifacts, Dict[str, object]]:
    inventory_df = filter_pdf_inventory(load_inventory(inventory_path))
    labels_df = load_labels(labels_csv, inventory_df)
    match_result = match_labels_to_inventory(inventory_df, labels_df)
    label_reconciliation = {
        "labels_matched": int(len(match_result.matched)),
        "labels_orphaned": int(len(match_result.orphaned)),
        "docs_unlabeled": int(len(match_result.unmatched_inventory)),
    }

    matched_df = match_result.matched.copy()
    if matched_df.empty:
        raise SystemExit("No matched labels found for training.")

    pdfs_df, _, _ = list_pdfs(inventory_path, extract_root=outputs_root)
    pdfs_df = pdfs_df.copy()
    pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)

    probe_docs, probe_id = _load_probe_docs(probe_ref, outputs_root)
    feature_df = extract_doc_features(
        pdfs_df[pdfs_df["rel_path"].isin(matched_df["rel_path"])],
        probe_docs,
        pages_sampled=pages_sampled,
        dpi=dpi,
        seed=seed,
    )

    matched_df["rel_path"] = matched_df["rel_path"].astype(str).map(normalize_rel_path)
    training_df = matched_df.merge(feature_df, on="rel_path", how="left")
    training_df["label_norm"] = training_df["label_raw"].map(normalize_label_value)
    training_df = training_df[training_df["label_norm"].notna()].copy()

    if training_df.empty:
        raise SystemExit("No valid labels found after normalization.")

    feature_columns = _feature_columns(training_df)
    X = training_df[feature_columns]
    y = training_df["label_norm"].astype(str)

    stratify_labels = y if y.value_counts().min() > 1 else None
    X_train, X_eval, y_train, y_eval = train_test_split(
        X,
        y,
        test_size=eval_split,
        random_state=seed,
        stratify=stratify_labels,
    )

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    multi_class="multinomial",
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=seed,
                ),
            ),
        ]
    )
    pipeline.fit(X_train, y_train)

    eval_payload = _evaluate_model(pipeline, X_eval, y_eval)

    model_dir, model_id = _model_output_dir(outputs_root, inventory_path)
    ensure_dir(model_dir)

    model_path = model_dir / "model.joblib"
    joblib.dump(pipeline, model_path)

    model_card = _build_model_card(
        training_df=training_df,
        feature_columns=feature_columns,
        eval_payload=eval_payload,
        label_reconciliation=label_reconciliation,
        inventory_path=inventory_path,
        probe_ref=probe_ref,
        probe_id=probe_id,
        pages_sampled=pages_sampled,
        dpi=dpi,
        seed=seed,
    )
    write_json(model_dir / "model_card.json", model_card)

    snapshot_cols = ["rel_path", "label_norm"] + feature_columns
    training_df[snapshot_cols].to_csv(model_dir / "training_snapshot.csv", index=False)

    pointer_payload = {
        "model_id": model_id,
        "run_dir": str(Path("models") / "doc_type" / model_id),
        "model_card": str(Path("models") / "doc_type" / model_id / "model_card.json"),
        "trained_at": model_card["timestamp"],
    }
    write_json(model_dir.parent / MODEL_POINTER, pointer_payload)

    artifacts = ModelArtifacts(
        model=pipeline,
        model_dir=model_dir,
        model_id=model_id,
        model_card=model_card,
    )
    return artifacts, eval_payload


def load_doc_type_model(model_ref: str, outputs_root: Path) -> Optional[ModelArtifacts]:
    model_path = resolve_doc_type_model_path(model_ref, outputs_root)
    if not model_path:
        return None
    model_dir = model_path.parent
    model_card = read_json(model_dir / "model_card.json")
    return ModelArtifacts(model=joblib.load(model_path), model_dir=model_dir, model_id=model_dir.name, model_card=model_card)


def predict_doc_types(
    *,
    pdfs_df: pd.DataFrame,
    probe_docs: Optional[pd.DataFrame],
    model_artifacts: ModelArtifacts,
    pages_sampled: int,
    dpi: int,
    seed: int,
    reason_features: bool = True,
) -> pd.DataFrame:
    feature_df = extract_doc_features(
        pdfs_df,
        probe_docs,
        pages_sampled=pages_sampled,
        dpi=dpi,
        seed=seed,
    )
    feature_columns = _feature_columns(feature_df)
    if not feature_columns:
        return pd.DataFrame()

    features = feature_df[feature_columns]
    probabilities = model_artifacts.model.predict_proba(features)
    class_labels = list(model_artifacts.model.named_steps["classifier"].classes_)

    proba_df = pd.DataFrame(probabilities, columns=class_labels)
    for label in DOC_TYPE_LABELS:
        if label not in proba_df.columns:
            proba_df[label] = 0.0

    proba_df = proba_df[DOC_TYPE_LABELS]
    predicted_label = proba_df.idxmax(axis=1)
    confidence = proba_df.max(axis=1)

    output = pd.concat(
        [
            feature_df[["rel_path", "doc_id", "top_level_folder", "pages_sampled", "dpi", "seed"]],
            pd.DataFrame({"predicted_label": predicted_label, "confidence": confidence}),
            proba_df.add_prefix("proba_"),
        ],
        axis=1,
    )

    if reason_features:
        output["reason_features"] = _build_reason_features(
            model_artifacts.model,
            features,
            predicted_label,
            feature_columns,
        )
    return output


def _build_reason_features(
    pipeline: Pipeline,
    features: pd.DataFrame,
    predicted_label: Iterable[str],
    feature_columns: List[str],
    top_k: int = 5,
) -> List[str]:
    transformed = pipeline[:-1].transform(features)
    classifier = pipeline.named_steps["classifier"]
    class_labels = list(classifier.classes_)
    coef = classifier.coef_

    reason_rows: List[str] = []
    for idx, label in enumerate(predicted_label):
        if label in class_labels:
            class_idx = class_labels.index(label)
        else:
            class_idx = 0
        contributions = coef[class_idx] * transformed[idx]
        top_indices = np.argsort(np.abs(contributions))[::-1][:top_k]
        reason = {
            feature_columns[i]: float(features.iloc[idx, i]) if i < len(feature_columns) else None
            for i in top_indices
        }
        reason_rows.append(json.dumps(reason))
    return reason_rows


def _evaluate_model(pipeline: Pipeline, X_eval: pd.DataFrame, y_eval: pd.Series) -> Dict[str, object]:
    if X_eval.empty:
        return {
            "confusion_matrix": [],
            "classification_report": {},
            "accuracy": None,
        }
    preds = pipeline.predict(X_eval)
    labels = sorted(set(y_eval))
    matrix = confusion_matrix(y_eval, preds, labels=labels)
    report = classification_report(y_eval, preds, labels=labels, output_dict=True, zero_division=0)
    return {
        "confusion_matrix": matrix.tolist(),
        "labels": labels,
        "classification_report": report,
        "accuracy": accuracy_score(y_eval, preds),
    }


def _feature_columns(df: pd.DataFrame) -> List[str]:
    excluded = {
        "rel_path",
        "doc_id",
        "top_level_folder",
        "label_norm",
        "label_raw",
        "label",
        "pages_sampled",
        "dpi",
        "seed",
        "predicted_label",
        "confidence",
    }
    columns = [col for col in df.columns if col not in excluded and df[col].dtype != object]
    return columns


def _model_output_dir(outputs_root: Path, inventory_path: Path) -> Tuple[Path, str]:
    outputs_root = Path(outputs_root)
    label = _infer_inventory_label(inventory_path)
    model_id = new_run_id("doc_type", label=label)
    model_dir = outputs_root / "models" / "doc_type" / model_id
    return model_dir, model_id


def _infer_inventory_label(inventory_path: Path) -> Optional[str]:
    summary = read_json(inventory_path.with_name("inventory_summary.json"))
    return summary.get("source_root_name") if summary else None


def _build_model_card(
    *,
    training_df: pd.DataFrame,
    feature_columns: List[str],
    eval_payload: Dict[str, object],
    label_reconciliation: Dict[str, int],
    inventory_path: Path,
    probe_ref: str,
    probe_id: str,
    pages_sampled: int,
    dpi: int,
    seed: int,
) -> Dict[str, object]:
    label_distribution = training_df["label_norm"].value_counts(dropna=False).to_dict()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(training_df)),
        "label_distribution": label_distribution,
        "features": feature_columns,
        "hyperparams": {
            "model": "LogisticRegression",
            "multi_class": "multinomial",
            "class_weight": "balanced",
            "imputer": "median",
            "scaler": "standard",
            "max_iter": 1000,
            "random_state": seed,
        },
        "feature_config": {
            "pages_sampled": pages_sampled,
            "dpi": dpi,
            "seed": seed,
        },
        "eval": eval_payload,
        "label_reconciliation": label_reconciliation,
        "inventory_reference": {
            "path": str(inventory_path),
            "run_id": inventory_identity(inventory_path),
        },
        "probe_reference": {
            "path": probe_ref,
            "run_id": probe_id,
        },
        "git_commit": current_git_commit(),
        "model_version": "doc_type_v1",
    }


def _load_probe_docs(value: str, outputs_root: Path) -> tuple[pd.DataFrame, str]:
    if not value or value.upper() == "NONE":
        return pd.DataFrame(), ""
    if value == "LATEST":
        latest = latest_probe(outputs_root)
        if latest:
            run_dir, pointer = latest
            docs = load_table(run_dir / "readiness_docs")
            return docs, pointer.get("probe_run_id", run_dir.name)
        return pd.DataFrame(), ""
    candidate = Path(value)
    if candidate.exists():
        if candidate.is_dir():
            docs = load_table(candidate / "readiness_docs")
            return docs, candidate.name
        return load_table(candidate), candidate.stem
    run_dir = outputs_root / "probes" / value
    if run_dir.exists():
        docs = load_table(run_dir / "readiness_docs")
        return docs, run_dir.name
    return pd.DataFrame(), ""


__all__ = [
    "DOC_TYPE_LABELS",
    "ModelArtifacts",
    "apply_doc_type_decision",
    "load_doc_type_model",
    "predict_doc_types",
    "resolve_doc_type_model_path",
    "train_doc_type_model",
]
