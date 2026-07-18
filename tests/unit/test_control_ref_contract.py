from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from scalescore.contracts.control_ref_consumer import (
    CanonicalControlRefEnvelope,
    ControlRefEnvelope,
    LegacyControlRefEnvelope,
)
from scalescore.models.scaling import ScaleScoreReport
from scalescore.storage.assessment_repository import SQLiteAssessmentRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "contracts" / "control-ref-v0.1.lock.json"
CONTRACT_RELATIVE_ROOT = Path("contracts/control-ref/v0.1")
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
VENDORED_BINDING = REPO_ROOT / "src" / "scalescore" / "contracts" / "control_ref.py"
CORPUS_ROOT = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT / "fixtures" / "corpus"
CONTROL_REF_ADAPTER = TypeAdapter(ControlRefEnvelope)


def _corpus_payload(name: str = "valid-canonical-synthetic.json") -> dict[str, object]:
    return json.loads((CORPUS_ROOT / name).read_text(encoding="utf-8"))


def _legacy_payload() -> dict[str, object]:
    return {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "ControlRef",
        "producer_capability": "workflow_context",
        "producer_system": "proofhouse-workflow-context",
        "canonical_owner": "workflow_context",
        "issued_at": "2026-07-17T16:00:00Z",
        "cache_policy": "summary_snapshot",
        "ref": {
            "ref_id": "control:tenant_demo:workflow_demo_001:approval",
            "ref_type": "control",
            "source_capability": "workflow_context",
            "organization_id": "tenant_demo",
            "environment_id": "test",
            "external_uri": "/api/workflows/workflow_demo_001/controls/approval",
            "snapshot_id": "control_snapshot_001",
            "version": "1",
            "created_at": "2026-07-17T15:58:00Z",
            "updated_at": "2026-07-17T15:59:00Z",
            "summary": "Historical repository-local control summary.",
            "control_assignment_id": "assignment_001",
            "control_id": "control_001",
            "control_key": "approval_gate",
            "control_family": "oversight",
            "control_statement": "Historical compatibility statement.",
            "implementation_status": "implemented",
            "evidence_status": "complete",
            "owner": "Historical owner",
            "workflow_id": "workflow_demo_001",
            "required_evidence_types": ["audit_log"],
        },
    }


def test_canonical_control_ref_corpus_matches_readiness_consumer() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    for relative_path, expected_digest in lock["sha256"].items():
        artifact = (
            VENDORED_BINDING
            if relative_path == "bindings/python/control_ref.py"
            else VENDORED_ROOT / relative_path
        )
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest

    contract_root = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
    digest_manifest = json.loads(
        (contract_root / "artifact-digests.json").read_text(encoding="utf-8")
    )
    for relative_path, expected_digest in digest_manifest["artifacts"].items():
        if relative_path == "bindings/python/control_ref.py":
            artifact = VENDORED_BINDING
        elif relative_path.startswith(f"{CONTRACT_RELATIVE_ROOT.as_posix()}/"):
            artifact = VENDORED_ROOT / relative_path
        else:
            continue
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest

    schema = json.loads((contract_root / "schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    index = json.loads((CORPUS_ROOT / "index.json").read_text(encoding="utf-8"))
    for case in index["cases"]:
        payload = _corpus_payload(case["file"])
        schema_errors = list(schema_validator.iter_errors(payload))
        if case["expected_valid"]:
            assert schema_errors == [], case["name"]
            canonical = CONTROL_REF_ADAPTER.validate_python(payload)
            assert isinstance(canonical, CanonicalControlRefEnvelope), case["name"]
        else:
            with pytest.raises(ValidationError):
                CONTROL_REF_ADAPTER.validate_python(payload)


def test_pin_only_payloads_preserve_exact_omission_shape() -> None:
    for fixture_name in (
        "valid-control-version-pin-only.json",
        "valid-control-snapshot-pin-only.json",
        "valid-workflow-version-pin-only.json",
    ):
        payload = _corpus_payload(fixture_name)
        envelope = CONTROL_REF_ADAPTER.validate_python(payload)

        assert envelope.model_dump(mode="json") == payload
        assert json.loads(envelope.model_dump_json()) == payload


@pytest.mark.parametrize(
    "path",
    [
        ("ref", "snapshot_id"),
        ("ref", "version"),
        ("ref", "workflow_ref", "ref", "snapshot_id"),
        ("ref", "workflow_ref", "ref", "version"),
    ],
)
def test_explicit_null_pin_is_rejected(path: tuple[str, ...]) -> None:
    payload = _corpus_payload()
    destination = payload
    for component in path[:-1]:
        destination = destination[component]
    destination[path[-1]] = None

    with pytest.raises(ValidationError, match="must be omitted rather than null"):
        CONTROL_REF_ADAPTER.validate_python(payload)


def test_malformed_canonical_payload_never_falls_back_to_legacy() -> None:
    payload = _corpus_payload()
    payload["ref"]["implementation_state"] = "approved"
    payload["ref"]["control_statement"] = "Must not activate legacy fallback."

    with pytest.raises(ValidationError):
        CONTROL_REF_ADAPTER.validate_python(payload)


def test_exact_legacy_shape_remains_observable_without_canonicalization() -> None:
    payload = _legacy_payload()

    envelope = CONTROL_REF_ADAPTER.validate_python(payload)

    assert isinstance(envelope, LegacyControlRefEnvelope)
    assert envelope.model_dump(mode="json") == payload
    assert json.loads(envelope.model_dump_json()) == payload
    assert "implementation_state" not in envelope.model_dump(mode="json")["ref"]
    assert "workflow_ref" not in envelope.model_dump(mode="json")["ref"]


def test_legacy_omitted_defaults_materialize_through_persistence(
    tmp_path: Path,
) -> None:
    payload = _legacy_payload()
    for field_name in (
        "contract_version",
        "contract_name",
        "producer_capability",
        "producer_system",
        "canonical_owner",
        "cache_policy",
    ):
        payload.pop(field_name)
    ref = payload["ref"]
    assert isinstance(ref, dict)
    for field_name in (
        "ref_type",
        "source_capability",
        "environment_id",
        "external_uri",
        "snapshot_id",
        "version",
        "owner",
        "required_evidence_types",
    ):
        ref.pop(field_name)

    envelope = CONTROL_REF_ADAPTER.validate_python(payload)
    expected = {
        **payload,
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "ControlRef",
        "producer_capability": "workflow_context",
        "producer_system": "proofhouse-workflow-context",
        "canonical_owner": "workflow_context",
        "cache_policy": "summary_snapshot",
        "ref": {
            **ref,
            "ref_type": "control",
            "source_capability": "workflow_context",
            "environment_id": "production",
            "external_uri": None,
            "snapshot_id": None,
            "version": None,
            "owner": None,
            "required_evidence_types": [],
        },
    }

    assert isinstance(envelope, LegacyControlRefEnvelope)
    assert envelope.model_dump(mode="json") == expected
    assert json.loads(envelope.model_dump_json()) == expected

    repository = SQLiteAssessmentRepository(tmp_path / "assessments.sqlite3")
    report = ScaleScoreReport(
        report_id="legacy-omitted-defaults-report",
        org_id="tenant_demo",
        overall_score=0.0,
        control_refs=[envelope],
    )
    repository.save_report(report, tenant_id="tenant_demo")
    loaded = repository.get_report("legacy-omitted-defaults-report", tenant_id="tenant_demo")

    assert loaded is not None
    loaded_envelope = loaded.control_refs[0]
    assert isinstance(loaded_envelope, LegacyControlRefEnvelope)
    loaded_payload = loaded_envelope.model_dump(mode="json")
    assert loaded_payload == expected
    assert {
        "workflow_ref",
        "implementation_state",
        "linkage_state",
    }.isdisjoint(loaded_payload["ref"])


def test_legacy_report_persistence_readback_remains_exact(tmp_path: Path) -> None:
    payload = _legacy_payload()
    envelope = CONTROL_REF_ADAPTER.validate_python(payload)
    repository = SQLiteAssessmentRepository(tmp_path / "assessments.sqlite3")
    report = ScaleScoreReport(
        report_id="legacy-control-report",
        org_id="tenant_demo",
        overall_score=0.0,
        control_refs=[envelope],
    )

    repository.save_report(report, tenant_id="tenant_demo")
    loaded = repository.get_report("legacy-control-report", tenant_id="tenant_demo")

    assert loaded is not None
    assert loaded.control_refs[0].model_dump(mode="json") == payload


def test_legacy_compatibility_rejects_shape_expansion() -> None:
    payload = _legacy_payload()
    payload["ref"]["governance_approval"] = "approved"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CONTROL_REF_ADAPTER.validate_python(payload)


def test_optional_fresh_contract_checkout_matches_vendored_artifacts() -> None:
    fresh_root_value = os.environ.get("PROOFHOUSE_CONTRACTS_ROOT")
    if fresh_root_value is None:
        return

    fresh_root = Path(fresh_root_value)
    fresh_contract_root = fresh_root / CONTRACT_RELATIVE_ROOT
    vendored_contract_root = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
    fresh_files = sorted(
        path.relative_to(fresh_contract_root)
        for path in fresh_contract_root.rglob("*")
        if path.is_file()
    )
    vendored_files = sorted(
        path.relative_to(vendored_contract_root)
        for path in vendored_contract_root.rglob("*")
        if path.is_file()
    )
    assert vendored_files == fresh_files
    for relative_path in fresh_files:
        assert (vendored_contract_root / relative_path).read_bytes() == (
            fresh_contract_root / relative_path
        ).read_bytes()

    fresh_binding = fresh_root / "bindings" / "python" / "control_ref.py"
    assert VENDORED_BINDING.read_bytes() == fresh_binding.read_bytes()
