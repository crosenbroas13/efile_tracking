import pandas as pd

from src.qa_metrics import (
    IssueConfig,
    categorize_file,
    detect_potential_issues,
    find_duplicate_groups,
)


def test_categorize_file_variants():
    assert categorize_file("pdf", None) == "pdf"
    assert categorize_file("txt", "text/plain") == "text"
    assert categorize_file("csv", "text/csv") == "csv"
    assert categorize_file("jpg", "image/jpeg") == "image"
    assert categorize_file("bin", "application/octet-stream") == "other"


def test_find_duplicate_groups_by_hash():
    df = pd.DataFrame(
        {
            "rel_path": ["a.txt", "b.txt", "c.txt"],
            "hash_value": ["abc", "abc", "xyz"],
            "size_bytes": [10, 10, 5],
        }
    )
    duplicates = find_duplicate_groups(df, use_hash=True)
    assert len(duplicates) == 1
    assert duplicates.iloc[0]["hash"] == "abc"
    assert duplicates.iloc[0]["count"] == 2


def test_detect_potential_issues_flags(tmp_path):
    now = pd.Timestamp.utcnow()
    future_time = (now + pd.Timedelta(days=1)).isoformat()
    df = pd.DataFrame(
        {
            "rel_path": ["zero.bin", "future.dat", "large.bin", "ok.txt"],
            "size_bytes": [0, 10, 1000, 5],
            "extension": ["bin", "dat", "bin", "txt"],
            "detected_mime": ["", "application/octet-stream", "application/octet-stream", "text/plain"],
            "modified_time": [now.isoformat(), future_time, now.isoformat(), now.isoformat()],
        }
    )

    issues = detect_potential_issues(df, IssueConfig(large_file_threshold=100))
    flagged_paths = set(issues["rel_path"])

    assert "zero.bin" in flagged_paths
    assert "future.dat" in flagged_paths
    assert "large.bin" in flagged_paths
    assert "ok.txt" not in flagged_paths
