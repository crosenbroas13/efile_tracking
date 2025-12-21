import json
from pathlib import Path

import pandas as pd

from src.probe_io import list_probe_runs, load_probe_run


def test_list_probe_runs_with_logs(tmp_path: Path):
    out_dir = tmp_path / "outputs"
    run_dir = out_dir / "probes" / "20240101_010101"
    run_dir.mkdir(parents=True)

    docs_df = pd.DataFrame(
        {
            "doc_id": ["doc-1"],
            "rel_path": ["file.pdf"],
            "page_count": [2],
            "classification": ["Text-based"],
        }
    )
    pages_df = pd.DataFrame({"doc_id": ["doc-1"], "page_num": [1], "has_text": [True]})
    docs_df.to_csv(run_dir / "readiness_docs.csv", index=False)
    pages_df.to_parquet(run_dir / "readiness_pages.parquet", index=False)

    summary = {"total_pdfs": 1, "total_pages": 2, "classification_counts": {"Text-based": 1}}
    run_log = {"probe_run_id": "20240101_010101", "timestamp": "2024-01-01T01:01:01Z"}
    (run_dir / "probe_summary.json").write_text(json.dumps(summary))
    (run_dir / "probe_run_log.json").write_text(json.dumps(run_log))

    runs = list_probe_runs(str(out_dir))
    assert len(runs) == 1
    assert runs[0]["probe_run_id"] == "20240101_010101"
    assert runs[0]["summary"].get("total_pdfs") == 1
    assert runs[0]["run_log"].get("timestamp") == "2024-01-01T01:01:01Z"

    docs_loaded, pages_loaded, summary_loaded, run_log_loaded = load_probe_run(
        str(out_dir), "20240101_010101"
    )
    assert not docs_loaded.empty
    assert not pages_loaded.empty
    assert summary_loaded["total_pages"] == 2
    assert run_log_loaded["probe_run_id"] == "20240101_010101"
