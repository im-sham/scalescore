#!/usr/bin/env python3
"""Vendor the exact local WorkflowRef V0.1 Contracts candidate without credentials."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
from pathlib import Path

EXPECTED_HEAD = "148549e8f117e0cc9b2d3725f9039720ae34b2e3"
EXPECTED_CONTRACT_TREE = "7b100000c0d979e3c025c61c0e6b40f11c4aad02"
REPO_ROOT = Path(__file__).resolve().parents[1]
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
DESTINATION_CONTRACT = VENDORED_ROOT / "contracts" / "workflow-ref" / "v0.1"
DESTINATION_BINDING = VENDORED_ROOT / "bindings" / "python" / "workflow_ref.py"
RUNTIME_BINDING = REPO_ROOT / "src" / "scalescore" / "contracts" / "generated" / "workflow_ref.py"


def _git(contracts_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=contracts_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_source(contracts_root: Path) -> None:
    if _git(contracts_root, "rev-parse", "HEAD") != EXPECTED_HEAD:
        raise SystemExit(f"Contracts checkout must be at exact candidate head {EXPECTED_HEAD}")
    if _git(contracts_root, "status", "--porcelain"):
        raise SystemExit("Contracts checkout must be clean")
    if (
        _git(contracts_root, "rev-parse", "HEAD:contracts/workflow-ref/v0.1")
        != EXPECTED_CONTRACT_TREE
    ):
        raise SystemExit(f"WorkflowRef contract tree must be {EXPECTED_CONTRACT_TREE}")


def _same_tree(source: Path, destination: Path) -> bool:
    comparison = filecmp.dircmp(source, destination)
    if (
        comparison.left_only
        or comparison.right_only
        or comparison.diff_files
        or comparison.funny_files
    ):
        return False
    return all(_same_tree(source / name, destination / name) for name in comparison.common_dirs)


def _check(source_contract: Path, source_binding: Path) -> None:
    if not DESTINATION_CONTRACT.is_dir() or not _same_tree(source_contract, DESTINATION_CONTRACT):
        raise SystemExit("Vendored WorkflowRef contract subtree differs from exact candidate")
    if not DESTINATION_BINDING.is_file() or not filecmp.cmp(
        source_binding, DESTINATION_BINDING, shallow=False
    ):
        raise SystemExit("Vendored WorkflowRef Python binding differs from exact candidate")
    if not RUNTIME_BINDING.is_file() or not filecmp.cmp(
        source_binding, RUNTIME_BINDING, shallow=False
    ):
        raise SystemExit("Installable WorkflowRef Python binding differs from exact candidate")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    contracts_root = args.contracts_root.resolve()
    _verify_source(contracts_root)
    source_contract = contracts_root / "contracts" / "workflow-ref" / "v0.1"
    source_binding = contracts_root / "bindings" / "python" / "workflow_ref.py"

    if args.check:
        _check(source_contract, source_binding)
        return 0

    if DESTINATION_CONTRACT.exists():
        shutil.rmtree(DESTINATION_CONTRACT)
    DESTINATION_CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_contract, DESTINATION_CONTRACT)
    DESTINATION_BINDING.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_binding, DESTINATION_BINDING)
    RUNTIME_BINDING.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_binding, RUNTIME_BINDING)
    _check(source_contract, source_binding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
