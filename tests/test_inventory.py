from src.config import InventoryConfig
from src.inventory import compute_file_id, scan_inventory, FileRecord
from src.manifest import build_summary


def test_ignore_patterns(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    kept = root / "keep.txt"
    kept.write_text("hello")
    ignored = root / "ignore.tmp"
    ignored.write_text("secret")

    config = InventoryConfig(
        root=root,
        out_dir=tmp_path / "out",
        hash_algorithm="none",
        ignore_patterns=["*.tmp"],
    )
    records, errors = scan_inventory(config)
    assert not errors
    rel_paths = {r.rel_path for r in records}
    assert "keep.txt" in rel_paths
    assert "ignore.tmp" not in rel_paths


def test_file_id_stability():
    rel_path = "folder/example.txt"
    size = 123
    mtime = 1690000000.0
    first = compute_file_id(rel_path, size, mtime)
    second = compute_file_id(rel_path, size, mtime)
    changed = compute_file_id(rel_path, size, mtime + 1)
    assert first == second
    assert first != changed


def test_summary_aggregation():
    records = [
        FileRecord(
            file_id="1",
            rel_path="a/file1.txt",
            abs_path="/tmp/a/file1.txt",
            top_level_folder="a",
            extension="txt",
            detected_mime="text/plain",
            size_bytes=10,
            created_time=None,
            modified_time=None,
            hash_value="",
            sample_hash=None,
        ),
        FileRecord(
            file_id="2",
            rel_path="b/file2.pdf",
            abs_path="/tmp/b/file2.pdf",
            top_level_folder="b",
            extension="pdf",
            detected_mime="application/pdf",
            size_bytes=30,
            created_time=None,
            modified_time=None,
            hash_value="",
            sample_hash=None,
        ),
    ]
    summary = build_summary(records, top_n=1)
    assert summary["totals"]["files"] == 2
    assert summary["totals"]["total_bytes"] == 40
    assert summary["counts_by_extension"]["txt"] == 1
    assert summary["counts_by_mime"]["application/pdf"] == 1
    assert summary["folders"]["a"]["files"] == 1
    assert summary["top_largest"][0]["rel_path"] == "b/file2.pdf"
