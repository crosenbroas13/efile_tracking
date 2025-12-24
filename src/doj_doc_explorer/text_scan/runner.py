from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from src.probe_readiness import list_pdfs

from ..utils.io import load_table, read_json
from ..utils.paths import normalize_rel_path
from .categorize import CategoryAccumulator
from .config import TextScanRunConfig
from .outputs import write_text_scan_outputs
from .quality import TextAccumulator, sanitize_snippet

_PDF_READER_SPEC = importlib.util.find_spec("pypdf")
if _PDF_READER_SPEC:
    from pypdf import PdfReader
else:  # pragma: no cover - optional dependency guard
    PdfReader = None


def run_text_scan(config: TextScanRunConfig) -> Tuple[pd.DataFrame, Dict[str, object]]:
    if PdfReader is None:
        raise SystemExit("pypdf is not installed; install it to run text_scan.")

    probe_docs = load_table(config.probe_run_dir / "readiness_docs")
    probe_pages = load_table(config.probe_run_dir / "readiness_pages")
    if probe_docs.empty:
        raise SystemExit("Probe readiness_docs not found or empty; run probe first.")

    pdfs_df, _, _ = list_pdfs(config.inventory_path, extract_root=config.outputs_root)
    pdfs_df["rel_path"] = pdfs_df["rel_path"].astype(str).map(normalize_rel_path)
    probe_docs["rel_path"] = probe_docs["rel_path"].astype(str).map(normalize_rel_path)
    if "rel_path" in probe_pages.columns:
        probe_pages["rel_path"] = probe_pages["rel_path"].astype(str).map(normalize_rel_path)

    candidates = probe_docs.copy()
    if "pages_with_text" in candidates.columns:
        candidates["pages_with_text"] = pd.to_numeric(candidates["pages_with_text"], errors="coerce").fillna(0)
    else:
        candidates["pages_with_text"] = 0

    candidates = candidates[candidates["pages_with_text"] >= config.min_text_pages].copy()
    if candidates.empty:
        raise SystemExit("No probe docs meet the minimum text page requirement.")

    candidates = candidates.merge(
        pdfs_df[["doc_id", "rel_path", "probe_path", "abs_path", "top_level_folder"]],
        on="rel_path",
        how="left",
        suffixes=("", "_inv"),
    )
    candidates["doc_id"] = candidates["doc_id"].fillna(candidates.get("doc_id_inv"))
    candidates["top_level_folder"] = candidates["top_level_folder"].fillna(candidates.get("top_level_folder_inv"))
    candidates["scan_path"] = candidates["probe_path"].fillna(candidates["abs_path"])

    candidate_rows = list(candidates.itertuples(index=False))
    if config.max_docs and config.max_docs > 0 and len(candidate_rows) > config.max_docs:
        rng = random.Random(config.seed)
        candidate_rows = rng.sample(candidate_rows, config.max_docs)

    pages_index = _build_pages_index(probe_pages)
    results: List[Dict[str, object]] = []
    errors: List[Dict[str, str]] = []

    for row in candidate_rows:
        row_dict = row._asdict()
        scan_path = row_dict.get("scan_path")
        rel_path = row_dict.get("rel_path", "")
        doc_id = row_dict.get("doc_id", "")
        if not scan_path:
            errors.append({"rel_path": rel_path, "error": "missing scan path"})
            continue
        pdf_path = Path(str(scan_path))
        if not pdf_path.exists():
            errors.append({"rel_path": rel_path, "error": f"missing file: {pdf_path}"})
            continue

        page_numbers = pages_index.get(rel_path, [])
        if not page_numbers:
            page_count = int(pd.to_numeric(row_dict.get("page_count"), errors="coerce") or 0)
            if page_count > 0:
                page_numbers = list(range(1, page_count + 1))
        if config.max_pages and config.max_pages > 0 and len(page_numbers) > config.max_pages:
            rng = random.Random(config.seed)
            page_numbers = sorted(rng.sample(page_numbers, config.max_pages))

        text_accumulator = TextAccumulator(config.quality)
        category_accumulator = CategoryAccumulator()
        snippet = ""
        scanned_pages = 0

        try:
            reader = PdfReader(str(pdf_path))
        except Exception as exc:
            errors.append({"rel_path": rel_path, "error": f"pdf open error: {exc}"})
            continue

        for page_num in page_numbers:
            if page_num < 1 or page_num > len(reader.pages):
                continue
            page = reader.pages[page_num - 1]
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if not text:
                continue
            scanned_pages += 1
            text_accumulator.update(text)
            category_accumulator.update(text)
            if config.store_snippet and not snippet:
                snippet = sanitize_snippet(text, config.quality)

        stats = text_accumulator.finalize(scanned_pages)
        content_pred = category_accumulator.finalize()

        record = {
            "doc_id": doc_id,
            "rel_path": rel_path,
            "top_level_folder": row_dict.get("top_level_folder") or "",
            "page_count": int(pd.to_numeric(row_dict.get("page_count"), errors="coerce") or 0),
            "pages_with_text": int(pd.to_numeric(row_dict.get("pages_with_text"), errors="coerce") or 0),
            **stats.as_dict(),
            **content_pred.as_dict(),
        }
        if config.store_snippet:
            record["text_snippet"] = snippet
        results.append(record)

    df = pd.DataFrame(results)
    meta = {
        "errors": errors,
        "error_count": len(errors),
        "docs_scanned": len(results),
        "docs_requested": len(candidate_rows),
    }
    return df, meta


def run_text_scan_and_save(config: TextScanRunConfig) -> Path:
    df, meta = run_text_scan(config)
    probe_run_id = config.probe_run_dir.name
    inventory_run_log = config.inventory_path.with_name("run_log.json")
    inventory_run_id = config.inventory_path.parent.name
    if inventory_run_log.exists():
        run_log = read_json(inventory_run_log)
        inventory_run_id = run_log.get("inventory_run_id") or inventory_run_id
    run_dir = write_text_scan_outputs(df, config, inventory_run_id=inventory_run_id, probe_run_id=probe_run_id)
    _write_meta(run_dir, meta)
    return run_dir


def _build_pages_index(probe_pages: pd.DataFrame) -> Dict[str, List[int]]:
    if probe_pages.empty or "rel_path" not in probe_pages.columns:
        return {}
    pages = probe_pages.copy()
    pages = pages[pages["has_text"] == True]  # noqa: E712
    pages["rel_path"] = pages["rel_path"].astype(str).map(normalize_rel_path)
    index: Dict[str, List[int]] = {}
    for rel_path, group in pages.groupby("rel_path"):
        page_nums = pd.to_numeric(group["page_num"], errors="coerce").fillna(0).astype(int)
        index[rel_path] = sorted([num for num in page_nums if num > 0])
    return index


def _write_meta(run_dir: Path, meta: Dict[str, object]) -> None:
    if not meta:
        return
    meta_path = run_dir / "text_scan_run_log.json"
    if not meta_path.exists():
        return
    existing = meta_path.read_text(encoding="utf-8")
    try:
        import json

        payload = json.loads(existing)
    except json.JSONDecodeError:
        return
    payload["meta"] = meta
    meta_path.write_text(json.dumps(payload, indent=2))


__all__ = ["run_text_scan", "run_text_scan_and_save"]
