"""PyCharm-friendly probe runner: edit two constants and run."""
from pathlib import Path

from doj_doc_explorer.config import ProbePaths, ProbeRunConfig
from doj_doc_explorer.probe.runner import run_probe_and_save
from doj_doc_explorer.utils.io import latest_inventory

INVENTORY = "LATEST"  # can be a path, run ID, or "LATEST"
OUT_DIR = Path("./outputs")


def main() -> None:
    inventory_value = INVENTORY
    if inventory_value == "LATEST":
        found = latest_inventory(OUT_DIR)
        if not found:
            raise SystemExit("No inventory found. Run an inventory first.")
        inventory_path = found
    else:
        candidate = Path(inventory_value)
        inventory_path = candidate if candidate.exists() else (OUT_DIR / "inventory" / inventory_value / "inventory.csv")
    config = ProbeRunConfig(paths=ProbePaths(inventory=inventory_path, outputs_root=OUT_DIR))
    run_dir = run_probe_and_save(config)
    print("Probe run complete")
    print(f"Outputs stored in: {run_dir}")


if __name__ == "__main__":
    main()
