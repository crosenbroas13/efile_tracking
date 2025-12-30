"""PyCharm-friendly name index runner: edit four constants and run."""
from pathlib import Path

from src.doj_doc_explorer.name_index.config import NameIndexRunConfig
from src.doj_doc_explorer.name_index.runner import run_name_index_and_save
from src.doj_doc_explorer.utils.io import latest_inventory, latest_probe, read_json

INVENTORY = "LATEST"  # can be a path, run ID, or "LATEST"
PROBE = "LATEST"  # can be a run ID, run folder, or "LATEST"
TEXT_SCAN = "LATEST"  # can be a run ID, run folder, or "LATEST"
OUT_DIR = Path("/Users/caylabroas/Desktop/E Files/DataFiles/Outputs")


def resolve_inventory_path(value: str, outputs_root: Path) -> Path:
    if value == "LATEST":
        found = latest_inventory(outputs_root)
        if not found:
            raise SystemExit("No inventory found. Run an inventory first.")
        return found
    candidate = Path(value)
    if candidate.exists():
        return candidate
    run_csv = outputs_root / "inventory" / value / "inventory.csv"
    if run_csv.exists():
        return run_csv
    raise SystemExit(f"Could not locate inventory at {value}")


def resolve_probe_run_dir(value: str, outputs_root: Path) -> Path:
    if value == "LATEST":
        latest = latest_probe(outputs_root)
        if latest:
            run_dir, _pointer = latest
            return run_dir
        raise SystemExit("No probe run found. Run a probe first.")
    candidate = Path(value)
    if candidate.exists():
        return candidate if candidate.is_dir() else candidate.parent
    run_dir = outputs_root / "probes" / value
    if run_dir.exists():
        return run_dir
    raise SystemExit(f"Could not locate probe run at {value}")


def resolve_text_scan_run_dir(value: str, outputs_root: Path) -> Path:
    if value == "LATEST":
        pointer = read_json(outputs_root / "text_scan" / "LATEST.json")
        run_dir = pointer.get("run_dir")
        if run_dir:
            candidate = outputs_root / run_dir
            if candidate.exists():
                return candidate
        raise SystemExit("No text scan run found. Run a text scan first.")
    candidate = Path(value)
    if candidate.exists():
        return candidate if candidate.is_dir() else candidate.parent
    run_dir = outputs_root / "text_scan" / value
    if run_dir.exists():
        return run_dir
    raise SystemExit(f"Could not locate text scan run at {value}")


def main() -> None:
    outputs_root = OUT_DIR
    inventory_path = resolve_inventory_path(INVENTORY, outputs_root)
    probe_run_dir = resolve_probe_run_dir(PROBE, outputs_root)
    text_scan_run_dir = resolve_text_scan_run_dir(TEXT_SCAN, outputs_root)
    config = NameIndexRunConfig(
        inventory_path=inventory_path,
        probe_run_dir=probe_run_dir,
        text_scan_run_dir=text_scan_run_dir,
        outputs_root=outputs_root,
    )
    run_dir = run_name_index_and_save(config)
    print("Name index complete")
    print(f"Run dir  : {run_dir}")
    print(f"Summary  : {run_dir / 'name_index_summary.json'}")


if __name__ == "__main__":
    main()
