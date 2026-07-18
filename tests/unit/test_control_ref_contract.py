from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

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

EXPECTED_LOCK = {
    "contract": "ControlRef",
    "contract_version": "proofhouse-shared-contracts/v0.1",
    "repository": "im-sham/proofhouse-contracts",
    "protected_ref": "main",
    "commit": "299384b1432fe4071d0d43ae4710e81feb9e31a5",
    "contracts_tree": "228a1fde26e9adbd9b0cda7b8fab9dfdf2633256",
    "contract_tree": "e03b662adb0f32522ecd0c87c2cf9fa90fd837ab",
    "vendor_root": "contracts/vendor/proofhouse-contracts",
    "sha256": {
        "bindings/python/control_ref.py": (
            "6db28ea5f861177a1748eb7724d95447c6b1b09a9cb0f3088c1617f2edc76cbd"
        ),
        "contracts/control-ref/v0.1/artifact-digests.json": (
            "e180d05ef1c5167da6e1ddc67daf1490484b33560c6023ea35851b0e6c7a56ac"
        ),
        "contracts/control-ref/v0.1/fixtures/corpus/index.json": (
            "1f12aef06eb90c5181e919571f2080d4af8b3f943fd86256022ebc9111ab1076"
        ),
        "contracts/control-ref/v0.1/provenance.json": (
            "7740eba201a5f73688f28ff51cadf10aaf362fe202ee371bc2f9dd2ea0c12da0"
        ),
        "contracts/control-ref/v0.1/schema.json": (
            "631c133c866472f6e1ea24e948cf2386a3c9f6b7c57314c05539cafda573c29f"
        ),
    },
}
NON_VENDORED_BINDING_DIGESTS = {
    "bindings/typescript/control-ref-validator.ts": (
        "7964f8acac118e880f45ae957511b0913d8e3a86c20a5b2f486bda61ee48ff9e"
    ),
    "bindings/typescript/control-ref.ts": (
        "df59e25a828de9ffedef52cf73f68d177b146fa2c88a31d791a6cd43a671d4fa"
    ),
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SAFE_CASE_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


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
    assert lock == EXPECTED_LOCK

    for relative_path, expected_digest in EXPECTED_LOCK["sha256"].items():
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
    assert set(digest_manifest) == {"algorithm", "artifacts", "format_version"}
    assert digest_manifest["algorithm"] == "sha256"
    assert digest_manifest["format_version"] == 1
    artifacts = digest_manifest["artifacts"]
    assert isinstance(artifacts, dict)
    assert artifacts

    listed_contract_artifacts: set[str] = set()
    for relative_path, expected_digest in artifacts.items():
        assert isinstance(relative_path, str)
        path = PurePosixPath(relative_path)
        assert "\\" not in relative_path
        assert "." not in path.parts
        assert not path.is_absolute()
        assert path.as_posix() == relative_path
        assert ".." not in path.parts
        assert isinstance(expected_digest, str)
        assert SHA256_PATTERN.fullmatch(expected_digest)

        if relative_path == "bindings/python/control_ref.py":
            artifact = VENDORED_BINDING
        elif relative_path in NON_VENDORED_BINDING_DIGESTS:
            assert expected_digest == NON_VENDORED_BINDING_DIGESTS[relative_path]
            continue
        else:
            assert relative_path.startswith(f"{CONTRACT_RELATIVE_ROOT.as_posix()}/")
            artifact = VENDORED_ROOT / relative_path
            listed_contract_artifacts.add(relative_path)
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest

    expected_contract_artifacts = {
        path.relative_to(VENDORED_ROOT).as_posix()
        for path in contract_root.rglob("*")
        if path.is_file() and path.name != "artifact-digests.json"
    }
    assert listed_contract_artifacts == expected_contract_artifacts

    schema = json.loads((contract_root / "schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    index = json.loads((CORPUS_ROOT / "index.json").read_text(encoding="utf-8"))
    assert set(index) == {"cases", "fixture_notice", "format_version"}
    assert index["format_version"] == 1
    cases = index["cases"]
    assert len(cases) == 40
    assert len({case["name"] for case in cases}) == 40
    assert len({case["file"] for case in cases}) == 40
    assert sum(case["expected_valid"] is True for case in cases) == 12
    assert sum(case["expected_valid"] is False for case in cases) == 28

    for case in cases:
        assert set(case) == {"coverage", "expected_valid", "file", "name"}
        assert SAFE_CASE_NAME_PATTERN.fullmatch(case["name"])
        assert type(case["expected_valid"]) is bool
        case_path = PurePosixPath(case["file"])
        assert case_path.name == case["file"]
        assert case_path.suffix == ".json"
        assert case_path.stem == case["name"]
        artifact_path = f"{CONTRACT_RELATIVE_ROOT.as_posix()}/fixtures/corpus/{case['file']}"
        assert artifact_path in artifacts

        raw_payload = (CORPUS_ROOT / case["file"]).read_bytes()
        payload = json.loads(raw_payload)
        schema_errors = list(schema_validator.iter_errors(payload))
        if case["expected_valid"]:
            assert schema_errors == [], case["name"]
            canonical = CanonicalControlRefEnvelope.model_validate_json(
                raw_payload, strict=True
            )
            assert isinstance(canonical, CanonicalControlRefEnvelope), case["name"]
            consumer = CONTROL_REF_ADAPTER.validate_json(raw_payload, strict=True)
            assert isinstance(consumer, CanonicalControlRefEnvelope), case["name"]
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
