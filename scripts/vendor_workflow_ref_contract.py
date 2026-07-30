#!/usr/bin/env python3
"""Vendor the exact protected-main WorkflowRef V0.1 Contracts publication."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

EXPECTED_COMMIT = "f9fae6c578cd0bbabf269933d6850ddb209b3c2e"
EXPECTED_ROOT_TREE = "ed2e4616d8680098aaa4f4e7ba83cfe5e07e966b"
EXPECTED_CONTRACTS_TREE = "d67979a7681fb872f9c60fff741d036d1eb2e0b5"
EXPECTED_CONTRACT_TREE = "7b100000c0d979e3c025c61c0e6b40f11c4aad02"
REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "contracts" / "workflow-ref-v0.1.lock.json"
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
CONTRACT_RELATIVE_ROOT = Path("contracts/workflow-ref/v0.1")
DESTINATION_CONTRACT = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
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
    expected_identities = (
        (("rev-parse", "HEAD"), EXPECTED_COMMIT, "Contracts commit"),
        (("rev-parse", "HEAD^{tree}"), EXPECTED_ROOT_TREE, "Contracts root tree"),
        (("rev-parse", "HEAD:contracts"), EXPECTED_CONTRACTS_TREE, "Contracts tree"),
        (
            ("rev-parse", "HEAD:contracts/workflow-ref/v0.1"),
            EXPECTED_CONTRACT_TREE,
            "WorkflowRef contract tree",
        ),
    )
    for arguments, expected, label in expected_identities:
        if _git(contracts_root, *arguments) != expected:
            raise SystemExit(f"{label} must be {expected}")
    if _git(contracts_root, "status", "--porcelain"):
        raise SystemExit("Contracts checkout must be clean")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate(contracts_root: Path, relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative_path in sorted(relative_paths):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((contracts_root / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_digests(contracts_root: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    expected_sha256 = lock["sha256"]
    contract_root = contracts_root / CONTRACT_RELATIVE_ROOT
    manifest_path = contract_root / "artifact-digests.json"
    if _sha256(manifest_path) != expected_sha256["artifact_manifest"]:
        raise SystemExit("WorkflowRef artifact manifest digest differs from publication lock")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    aggregate_fields = {
        "schema_sha256": "schema",
        "corpus_sha256": "corpus",
        "artifact_set_sha256": "artifact_set",
        "generated_binding_sha256": "generated_bindings",
    }
    for manifest_field, lock_field in aggregate_fields.items():
        if manifest.get(manifest_field) != expected_sha256[lock_field]:
            raise SystemExit(f"WorkflowRef {manifest_field} differs from publication lock")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise SystemExit("WorkflowRef artifact manifest must contain path digests")
    for relative_path, expected_digest in artifacts.items():
        artifact = contracts_root / relative_path
        if not artifact.is_file() or _sha256(artifact) != expected_digest:
            raise SystemExit(f"WorkflowRef artifact digest differs: {relative_path}")

    corpus_paths = [
        relative_path
        for relative_path in artifacts
        if relative_path.startswith("contracts/workflow-ref/v0.1/fixtures/corpus/")
    ]
    binding_paths = [
        relative_path for relative_path in artifacts if relative_path.startswith("bindings/")
    ]
    aggregates = {
        "artifact_set": _aggregate(contracts_root, list(artifacts)),
        "corpus": _aggregate(contracts_root, corpus_paths),
        "generated_bindings": _aggregate(contracts_root, binding_paths),
    }
    for lock_field, actual_digest in aggregates.items():
        if actual_digest != expected_sha256[lock_field]:
            raise SystemExit(f"WorkflowRef {lock_field} digest differs from publication lock")

    schema_path = contract_root / "schema.json"
    corpus_index_path = contract_root / "fixtures" / "corpus" / "index.json"
    python_binding_path = contracts_root / "bindings" / "python" / "workflow_ref.py"
    retained_paths = {
        "schema": schema_path,
        "corpus_index": corpus_index_path,
        "python_binding": python_binding_path,
    }
    for lock_field, path in retained_paths.items():
        if _sha256(path) != expected_sha256[lock_field]:
            raise SystemExit(f"WorkflowRef {lock_field} digest differs from publication lock")


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
        raise SystemExit("Vendored WorkflowRef contract subtree differs from exact publication")
    if not DESTINATION_BINDING.is_file() or not filecmp.cmp(
        source_binding, DESTINATION_BINDING, shallow=False
    ):
        raise SystemExit("Vendored WorkflowRef Python binding differs from exact publication")
    if not RUNTIME_BINDING.is_file() or not filecmp.cmp(
        source_binding, RUNTIME_BINDING, shallow=False
    ):
        raise SystemExit("Installable WorkflowRef Python binding differs from exact publication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    contracts_root = args.contracts_root.resolve()
    _verify_source(contracts_root)
    _verify_digests(contracts_root)
    source_contract = contracts_root / CONTRACT_RELATIVE_ROOT
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
