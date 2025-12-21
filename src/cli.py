"""Thin wrappers around the primary doj_doc_explorer CLI.

This module keeps the legacy import paths used in tests and helper tools
while delegating all real work to the maintained ``doj_doc_explorer.cli``
entry points. That way the command surface stays in one place instead of
being duplicated across multiple modules.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.doj_doc_explorer import cli as core_cli


def run_inventory(args: argparse.Namespace) -> None:
    """Run an inventory using the shared doj_doc_explorer implementation."""
    try:
        core_cli.run_inventory_cmd(args)
    except ValueError as exc:
        # Preserve the legacy SystemExit behavior expected by tests and wrappers.
        raise SystemExit(str(exc)) from exc

    # Legacy compatibility: mirror the aggregated log to the output root where
    # older tooling expects it.
    out_dir = Path(args.out)
    inventory_log = out_dir / "inventory" / "run_log.jsonl"
    legacy_log = out_dir / "run_log.jsonl"
    if inventory_log.exists():
        legacy_log.write_bytes(inventory_log.read_bytes())


def run_probe_cli(args: argparse.Namespace) -> None:
    """Run a probe using the shared doj_doc_explorer implementation."""

    core_cli.run_probe_cmd(args)


def build_parser() -> argparse.ArgumentParser:
    """Reuse the maintained parser so help output stays consistent."""

    return core_cli.build_parser()


def main(argv=None):
    core_cli.main(argv)


if __name__ == "__main__":
    main()
