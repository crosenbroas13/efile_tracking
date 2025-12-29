"""PyCharm-friendly inventory runner: edit two constants and run."""
from pathlib import Path

from doj_doc_explorer.inventory.runner import InventoryRunner

DATA_ROOT = Path("./data")
OUT_DIR = Path("./outputs")


def main() -> None:
    runner = InventoryRunner()
    config = runner.create_config(root=DATA_ROOT, out_dir=OUT_DIR)
    result = runner.run(config)
    print("Inventory finished")
    print(f"Run dir  : {result.run_dir}")
    print(f"CSV      : {result.csv_path}")
    print(f"Summary  : {result.summary_path}")


if __name__ == "__main__":
    main()
