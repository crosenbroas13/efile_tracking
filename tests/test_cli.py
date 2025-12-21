import argparse
from pathlib import Path

import pytest

from src import cli


def build_args(root: Path, **overrides) -> argparse.Namespace:
    defaults = {
        "root": str(root),
        "out": str(root / "out"),
        "hash": "none",
        "sample_bytes": 0,
        "ignore": [],
        "follow_symlinks": False,
        "max_files": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_run_inventory_requires_existing_folder(tmp_path):
    missing_root = tmp_path / "missing"
    args = build_args(missing_root)
    with pytest.raises(SystemExit):
        cli.run_inventory(args)


def test_run_inventory_requires_directory(tmp_path):
    file_root = tmp_path / "not_a_dir"
    file_root.write_text("not a directory")
    args = build_args(file_root)
    with pytest.raises(SystemExit):
        cli.run_inventory(args)


def test_run_inventory_rejects_non_positive_max_files(tmp_path):
    args = build_args(tmp_path, max_files=0)
    with pytest.raises(SystemExit):
        cli.run_inventory(args)


def test_run_inventory_writes_outputs(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "example.txt").write_text("hello world")

    args = build_args(data_root)
    cli.run_inventory(args)

    out_dir = Path(args.out)
    assert (out_dir / "inventory.csv").exists()
    assert (out_dir / "inventory_summary.json").exists()
    assert (out_dir / "run_log.jsonl").exists()
