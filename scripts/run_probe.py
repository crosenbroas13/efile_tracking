"""Convenience runner for probe readiness checks."""

from pathlib import Path

from src.probe_config import ProbeConfig
from src.probe_runner import run_probe_and_save

INVENTORY_PATH = "./outputs/inventory.csv"
OUT_DIR = "./outputs"


def main() -> None:
    config = ProbeConfig(inventory_path=Path(INVENTORY_PATH), output_root=Path(OUT_DIR))
    run_dir = run_probe_and_save(config)
    print("Probe run complete")
    print(f"Outputs stored in: {run_dir}")


if __name__ == "__main__":
    main()
