from __future__ import annotations

import pandas as pd


def apply_doc_type_decision(docs_df: pd.DataFrame, *, min_confidence: float) -> pd.DataFrame:
    docs_df = docs_df.copy()

    def _choose(row: pd.Series) -> tuple[str, str]:
        truth = str(row.get("doc_type_truth") or "").strip()
        if truth:
            return truth, "TRUTH"
        model_pred = str(row.get("doc_type_model_pred") or "").strip()
        model_conf = row.get("model_confidence")
        if model_pred and model_conf is not None and not pd.isna(model_conf) and float(model_conf) >= min_confidence:
            return model_pred, "MODEL"
        heuristic = str(row.get("doc_type_heuristic") or "").strip()
        return heuristic, "HEURISTIC"

    decisions = docs_df.apply(_choose, axis=1, result_type="expand")
    docs_df["doc_type_final"] = decisions[0]
    docs_df["doc_type_source"] = decisions[1]
    return docs_df


__all__ = ["apply_doc_type_decision"]
