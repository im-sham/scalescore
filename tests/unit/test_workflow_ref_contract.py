from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "contracts" / "workflow-ref-v0.1.lock.json"
CONTRACT_RELATIVE_ROOT = Path("contracts/workflow-ref/v0.1")
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
VENDORED_BINDING = VENDORED_ROOT / "bindings" / "python" / "workflow_ref.py"
RUNTIME_BINDING = REPO_ROOT / "src" / "scalescore" / "contracts" / "generated" / "workflow_ref.py"
EXPORTER = REPO_ROOT / "scripts" / "vendor_workflow_ref_contract.py"
EXPECTED_COMMIT = "f9fae6c578cd0bbabf269933d6850ddb209b3c2e"
EXPECTED_ROOT_TREE = "ed2e4616d8680098aaa4f4e7ba83cfe5e07e966b"
EXPECTED_CONTRACTS_TREE = "d67979a7681fb872f9c60fff741d036d1eb2e0b5"
EXPECTED_CONTRACT_TREE = "7b100000c0d979e3c025c61c0e6b40f11c4aad02"
EXPECTED_CORPUS_CASES = 95


def _binding_module():
    return importlib.import_module("scalescore.contracts.workflow_ref")


def _exporter_module():
    spec = importlib.util.spec_from_file_location("vendor_workflow_ref_contract", EXPORTER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_digest_layout(
    exporter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    contracts_root = tmp_path / "contracts-root"
    shutil.copytree(VENDORED_ROOT, contracts_root)
    manifest_path = contracts_root / CONTRACT_RELATIVE_ROOT / "artifact-digests.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {
        relative_path: expected_digest
        for relative_path, expected_digest in manifest["artifacts"].items()
        if (contracts_root / relative_path).is_file()
    }
    corpus_paths = [
        relative_path
        for relative_path in artifacts
        if relative_path.startswith("contracts/workflow-ref/v0.1/fixtures/corpus/")
    ]
    binding_paths = [
        relative_path for relative_path in artifacts if relative_path.startswith("bindings/")
    ]
    manifest["artifacts"] = artifacts
    manifest["artifact_set_sha256"] = exporter._aggregate(contracts_root, list(artifacts))
    manifest["corpus_sha256"] = exporter._aggregate(contracts_root, corpus_paths)
    manifest["generated_binding_sha256"] = exporter._aggregate(contracts_root, binding_paths)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock["sha256"]["artifact_manifest"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    lock["sha256"]["artifact_set"] = manifest["artifact_set_sha256"]
    lock["sha256"]["corpus"] = manifest["corpus_sha256"]
    lock["sha256"]["generated_bindings"] = manifest["generated_binding_sha256"]
    lock_path = tmp_path / "workflow-ref-v0.1.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(exporter, "LOCK_PATH", lock_path)
    return contracts_root


def test_broad_workflow_models_are_explicitly_legacy_only() -> None:
    scaling = importlib.import_module("scalescore.models.scaling")

    assert hasattr(scaling, "LegacyWorkflowRef")
    assert hasattr(scaling, "LegacyWorkflowRefEnvelope")
    assert not hasattr(scaling, "WorkflowRef")
    assert not hasattr(scaling, "WorkflowRefEnvelope")


def test_publication_lock_records_exact_provenance_digests_and_rollback() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    assert lock["status"] == "protected_main_publication"
    assert lock["published"] is True
    assert lock["protected_ref"] == "main"
    assert lock["commit"] == EXPECTED_COMMIT
    assert lock["root_tree"] == EXPECTED_ROOT_TREE
    assert lock["contracts_tree"] == EXPECTED_CONTRACTS_TREE
    assert lock["contract_tree"] == EXPECTED_CONTRACT_TREE
    assert lock["binding_blob"] == "5c3e6e9f04c01837f7e34d9fd588c6586fef7d4b"
    assert lock["review"] == {
        "pull_request": 15,
        "head": "148549e8f117e0cc9b2d3725f9039720ae34b2e3",
        "head_tree": EXPECTED_ROOT_TREE,
        "base": "1b0c4c7fea1fa6f20b82556acae1e6cf9c509f99",
        "ci_run": 30555945810,
        "independent_review": "approved",
    }
    assert lock["authority"] == {
        "usmi_commit": "af1cf7e87e2848a84048a27335cdff533d2d6e36",
        "decision": "decisions/2026-07-29-wp-ri-03-workflow-ref-d12-authority-candidate.md",
        "clarification": (
            "decisions/2026-07-30-scaffold-product-role-and-workflow-ref-d12-clarification.md"
        ),
    }
    assert lock["sha256"] == {
        "schema": "18ad1178598eea77c5f160afd5f0329ca3c3d388ada7593c18a1d7d4aeecc9cd",
        "corpus_index": "d8016551d1eb0246a09c1907a55cde63ac60e07989c9b04205666f8e6b65abcc",
        "corpus": "1e206ca9601fba7d177e1fd920c41f9585d8c603424dc1898eb79a4cc376e2bc",
        "artifact_manifest": "bea2e1ad16a36db9a8ef35e110257ea6442d47e9b36a1c267ee9f83daa652e6a",
        "artifact_set": "a093722cbbd236d0ba10f85da77a84ab0b9effa5a0a0d7952fcaa9e3e5781b4f",
        "generated_bindings": "6794e22f4c70f1931ee49d5ecae8db5a087b1c57bc5861315e4f43a4b490ce2c",
        "python_binding": "5be783ce419b59b7b3e439b6d970afc78f9953ad60a767c639507bdea5a86247",
    }
    assert lock["compatibility"] == {
        "surface": "LegacyWorkflowRefEnvelope summary_snapshot",
        "route": "/api/v1/assessments/mila/workflow",
        "window": "one_release",
        "canonical_fallback": False,
    }
    assert lock["rollback"] == {
        "readiness_base": "47388ddfab0a1cc5eea7807f8de819f0753f2825",
        "strategy": (
            "revert the consumer branch and restore the explicitly noncanonical legacy "
            "summary_snapshot route and stored-report readback; never route malformed "
            "canonical input to legacy or relabel nested alignment as canonical"
        ),
    }
    assert lock["publication"] == {
        "protected_commit_verified": True,
        "artifact_bytes_changed": False,
        "artifact_digests_changed": False,
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (("rev-parse", "HEAD"), EXPECTED_COMMIT),
        (("rev-parse", "HEAD^{tree}"), EXPECTED_ROOT_TREE),
        (("rev-parse", "HEAD:contracts"), EXPECTED_CONTRACTS_TREE),
        (("rev-parse", "HEAD:contracts/workflow-ref/v0.1"), EXPECTED_CONTRACT_TREE),
    ],
)
def test_exporter_fails_closed_on_each_provenance_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    query: tuple[str, str],
    expected: str,
) -> None:
    exporter = _exporter_module()
    provenance = {
        ("rev-parse", "HEAD"): EXPECTED_COMMIT,
        ("rev-parse", "HEAD^{tree}"): EXPECTED_ROOT_TREE,
        ("rev-parse", "HEAD:contracts"): EXPECTED_CONTRACTS_TREE,
        ("rev-parse", "HEAD:contracts/workflow-ref/v0.1"): EXPECTED_CONTRACT_TREE,
        ("status", "--porcelain"): "",
    }
    provenance[query] = f"{expected}-drift"
    monkeypatch.setattr(exporter, "_git", lambda _root, *arguments: provenance[arguments])

    with pytest.raises(SystemExit, match="must be"):
        exporter._verify_source(tmp_path)


def test_exporter_fails_closed_on_path_keyed_artifact_digest_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exporter = _exporter_module()
    contracts_root = _copy_digest_layout(exporter, monkeypatch, tmp_path)
    relative_path = CONTRACT_RELATIVE_ROOT / "schema.json"
    (contracts_root / relative_path).write_bytes(b"{}\n")

    with pytest.raises(
        SystemExit,
        match=f"WorkflowRef artifact digest differs: {relative_path.as_posix()}",
    ):
        exporter._verify_digests(contracts_root)


def test_exporter_fails_closed_on_recomputed_aggregate_digest_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exporter = _exporter_module()
    contracts_root = _copy_digest_layout(exporter, monkeypatch, tmp_path)
    aggregate = exporter._aggregate
    aggregate_calls = 0

    def drift_first_aggregate(root: Path, relative_paths: list[str]) -> str:
        nonlocal aggregate_calls
        aggregate_calls += 1
        actual = aggregate(root, relative_paths)
        return "0" * 64 if aggregate_calls == 1 else actual

    monkeypatch.setattr(exporter, "_aggregate", drift_first_aggregate)

    with pytest.raises(
        SystemExit,
        match="WorkflowRef artifact_set digest differs from publication lock",
    ):
        exporter._verify_digests(contracts_root)


def test_exporter_fails_closed_on_manifest_digest_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exporter = _exporter_module()
    contracts_root = _copy_digest_layout(exporter, monkeypatch, tmp_path)
    manifest_path = contracts_root / CONTRACT_RELATIVE_ROOT / "artifact-digests.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    with pytest.raises(
        SystemExit,
        match="WorkflowRef artifact manifest digest differs from publication lock",
    ):
        exporter._verify_digests(contracts_root)


@pytest.mark.parametrize("drift_target", ["vendored_binding", "runtime_binding"])
def test_exporter_fails_closed_on_binding_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift_target: str,
) -> None:
    exporter = _exporter_module()
    source_contract = tmp_path / "source-contract"
    source_binding = tmp_path / "source-workflow_ref.py"
    destination_contract = tmp_path / "destination-contract"
    destination_binding = tmp_path / "destination-workflow_ref.py"
    runtime_binding = tmp_path / "runtime-workflow_ref.py"
    shutil.copytree(VENDORED_ROOT / CONTRACT_RELATIVE_ROOT, source_contract)
    shutil.copytree(source_contract, destination_contract)
    source_binding.write_bytes(VENDORED_BINDING.read_bytes())
    destination_binding.write_bytes(source_binding.read_bytes())
    runtime_binding.write_bytes(source_binding.read_bytes())
    if drift_target == "vendored_binding":
        destination_binding.write_bytes(b"# drift\n")
    else:
        runtime_binding.write_bytes(b"# drift\n")
    monkeypatch.setattr(exporter, "DESTINATION_CONTRACT", destination_contract)
    monkeypatch.setattr(exporter, "DESTINATION_BINDING", destination_binding)
    monkeypatch.setattr(exporter, "RUNTIME_BINDING", runtime_binding)

    with pytest.raises(SystemExit, match="binding differs"):
        exporter._check(source_contract, source_binding)


def test_exporter_fails_closed_on_subtree_path_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exporter = _exporter_module()
    source_contract = tmp_path / "source-contract"
    destination_contract = tmp_path / "destination-contract"
    source_binding = tmp_path / "source-workflow_ref.py"
    destination_binding = tmp_path / "destination-workflow_ref.py"
    runtime_binding = tmp_path / "runtime-workflow_ref.py"
    shutil.copytree(VENDORED_ROOT / CONTRACT_RELATIVE_ROOT, source_contract)
    shutil.copytree(source_contract, destination_contract)
    (destination_contract / "unexpected.json").write_text("{}\n", encoding="utf-8")
    source_binding.write_bytes(VENDORED_BINDING.read_bytes())
    destination_binding.write_bytes(source_binding.read_bytes())
    runtime_binding.write_bytes(source_binding.read_bytes())
    monkeypatch.setattr(exporter, "DESTINATION_CONTRACT", destination_contract)
    monkeypatch.setattr(exporter, "DESTINATION_BINDING", destination_binding)
    monkeypatch.setattr(exporter, "RUNTIME_BINDING", runtime_binding)

    with pytest.raises(SystemExit, match="subtree differs"):
        exporter._check(source_contract, source_binding)


def test_exact_95_case_published_corpus_matches_schema_and_binding() -> None:
    binding = _binding_module()
    contract_root = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
    schema = json.loads((contract_root / "schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    corpus_root = contract_root / "fixtures" / "corpus"
    index = json.loads((corpus_root / "index.json").read_text(encoding="utf-8"))

    assert len(index["cases"]) == EXPECTED_CORPUS_CASES
    for case in index["cases"]:
        payload = json.loads((corpus_root / case["file"]).read_text(encoding="utf-8"))
        schema_valid = not list(validator.iter_errors(payload))
        if case["expected_valid"]:
            assert schema_valid, case["name"]
            binding.WorkflowRefEnvelope.model_validate(payload)
        else:
            with pytest.raises(ValidationError, match=".+"):
                binding.WorkflowRefEnvelope.model_validate(payload)


def test_vendored_published_bytes_match_lock_and_manifest() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    contract_root = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
    manifest_path = contract_root / "artifact-digests.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == lock["sha256"]["artifact_manifest"]
    )
    assert manifest["schema_sha256"] == lock["sha256"]["schema"]
    assert manifest["corpus_sha256"] == lock["sha256"]["corpus"]
    assert manifest["artifact_set_sha256"] == lock["sha256"]["artifact_set"]
    assert manifest["generated_binding_sha256"] == lock["sha256"]["generated_bindings"]
    assert (
        hashlib.sha256(VENDORED_BINDING.read_bytes()).hexdigest()
        == lock["sha256"]["python_binding"]
    )
    assert RUNTIME_BINDING.read_bytes() == VENDORED_BINDING.read_bytes()
    for relative_path, expected_digest in manifest["artifacts"].items():
        if relative_path == "bindings/python/workflow_ref.py":
            artifact = VENDORED_BINDING
        elif relative_path.startswith(f"{CONTRACT_RELATIVE_ROOT.as_posix()}/"):
            artifact = VENDORED_ROOT / relative_path
        else:
            continue
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest, relative_path


def test_credential_free_exporter_check_accepts_exact_local_publication() -> None:
    contracts_root_value = os.environ.get("PROOFHOUSE_CONTRACTS_ROOT")
    if contracts_root_value is None:
        return

    result = subprocess.run(
        [
            sys.executable,
            str(EXPORTER),
            "--contracts-root",
            contracts_root_value,
            "--check",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
