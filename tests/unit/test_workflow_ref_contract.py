from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "contracts" / "workflow-ref-v0.1-candidate.lock.json"
CONTRACT_RELATIVE_ROOT = Path("contracts/workflow-ref/v0.1")
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
VENDORED_BINDING = VENDORED_ROOT / "bindings" / "python" / "workflow_ref.py"
RUNTIME_BINDING = REPO_ROOT / "src" / "scalescore" / "contracts" / "generated" / "workflow_ref.py"
EXPORTER = REPO_ROOT / "scripts" / "vendor_workflow_ref_candidate.py"
EXPECTED_HEAD = "148549e8f117e0cc9b2d3725f9039720ae34b2e3"
EXPECTED_CONTRACT_TREE = "7b100000c0d979e3c025c61c0e6b40f11c4aad02"
EXPECTED_CORPUS_CASES = 95


def _binding_module():
    return importlib.import_module("scalescore.contracts.workflow_ref")


def test_broad_workflow_models_are_explicitly_legacy_only() -> None:
    scaling = importlib.import_module("scalescore.models.scaling")

    assert hasattr(scaling, "LegacyWorkflowRef")
    assert hasattr(scaling, "LegacyWorkflowRefEnvelope")
    assert not hasattr(scaling, "WorkflowRef")
    assert not hasattr(scaling, "WorkflowRefEnvelope")


def test_candidate_lock_records_exact_provenance_digests_and_rollback() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    assert lock["status"] == "reviewed_candidate_prepublication"
    assert lock["published"] is False
    assert lock["source"] == {
        "base": "1b0c4c7fea1fa6f20b82556acae1e6cf9c509f99",
        "head": EXPECTED_HEAD,
        "draft_pull_request": 15,
        "contracts_tree": "d67979a7681fb872f9c60fff741d036d1eb2e0b5",
        "contract_tree": EXPECTED_CONTRACT_TREE,
        "binding_blob": "5c3e6e9f04c01837f7e34d9fd588c6586fef7d4b",
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
    assert lock["rollback"]["readiness_base"] == ("47388ddfab0a1cc5eea7807f8de819f0753f2825")


def test_exact_95_case_candidate_corpus_matches_schema_and_binding() -> None:
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


def test_vendored_candidate_bytes_match_lock_and_manifest() -> None:
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


def test_credential_free_exporter_check_accepts_exact_local_candidate() -> None:
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
