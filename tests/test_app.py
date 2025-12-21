from pathlib import Path

from src.app import InventoryRunner


def test_resolves_missing_leading_slash(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()

    runner = InventoryRunner()
    config = runner.create_config(
        root=str(data_root).lstrip("/"),
        out_dir=tmp_path / "out",
    )

    assert config.root == data_root


def test_resolves_out_dir_without_leading_slash(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()

    intended_out = tmp_path / "results"
    relative_out = str(intended_out).lstrip("/")

    runner = InventoryRunner()
    config = runner.create_config(
        root=data_root,
        out_dir=relative_out,
    )

    assert config.out_dir == intended_out
