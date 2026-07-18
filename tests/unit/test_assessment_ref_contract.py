from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from scalescore.contracts.assessment_ref import AssessmentRefEnvelope

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "contracts" / "assessment-ref-v0.1.lock.json"
CONTRACT_RELATIVE_ROOT = Path("contracts/assessment-ref/v0.1")
VENDORED_ROOT = REPO_ROOT / "contracts" / "vendor" / "proofhouse-contracts"
VENDORED_BINDING = REPO_ROOT / "src" / "scalescore" / "contracts" / "assessment_ref.py"


def _canonical_payload(
    *, score: float = 72.0, grade: str = "C", status: str = "watch"
) -> dict[str, object]:
    return {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "AssessmentRef",
        "producer_capability": "readiness",
        "producer_system": "proofhouse-readiness",
        "canonical_owner": "readiness",
        "issued_at": "2026-07-17T16:00:00Z",
        "cache_policy": "summary_snapshot",
        "ref": {
            "ref_id": "assessment:tenant_demo:assessment_demo_001",
            "ref_type": "assessment",
            "source_capability": "readiness",
            "organization_id": "tenant_demo",
            "environment_id": "test",
            "external_uri": "/api/v1/assessments/assessment_demo_001",
            "snapshot_id": "assessment_demo_001",
            "version": "1.1",
            "created_at": "2026-07-17T16:00:00Z",
            "summary": "Synthetic workflow readiness diagnostic summary.",
            "assessment_id": "assessment_demo_001",
            "workflow_ref": {
                "contract_version": "proofhouse-shared-contracts/v0.1",
                "contract_name": "WorkflowRef",
                "producer_capability": "workflow_context",
                "producer_system": "proofhouse-workflow-context",
                "canonical_owner": "workflow_context",
                "issued_at": "2026-07-17T15:59:00Z",
                "cache_policy": "summary_snapshot",
                "ref": {
                    "ref_id": "workflow:tenant_demo:workflow_demo_001",
                    "ref_type": "workflow",
                    "source_capability": "workflow_context",
                    "organization_id": "tenant_demo",
                    "environment_id": "test",
                    "external_uri": "/api/workflows/workflow_demo_001",
                    "snapshot_id": "workflow_snapshot_demo_001",
                    "version": "1.0",
                },
            },
            "assessment_type": "workflow_readiness",
            "score": score,
            "grade": grade,
            "status": status,
            "top_blockers": ["Synthetic evidence freshness gap"],
            "top_reasons": ["Synthetic control coverage is partial"],
        },
    }


@pytest.mark.parametrize(
    ("score", "grade", "status"),
    [
        (0.0, "F", "blocked"),
        (49.999, "F", "blocked"),
        (50.0, "F", "at_risk"),
        (59.999, "F", "at_risk"),
        (60.0, "D", "at_risk"),
        (64.999, "D", "at_risk"),
        (65.0, "D", "watch"),
        (69.999, "D", "watch"),
        (70.0, "C", "watch"),
        (79.999, "C", "watch"),
        (80.0, "B", "ready"),
        (89.999, "B", "ready"),
        (90.0, "A", "ready"),
        (100.0, "A", "ready"),
    ],
)
def test_assessment_ref_accepts_protected_score_boundaries(
    score: float, grade: str, status: str
) -> None:
    envelope = AssessmentRefEnvelope.model_validate(
        _canonical_payload(score=score, grade=grade, status=status)
    )

    assert envelope.ref.score == score
    assert envelope.ref.grade == grade
    assert envelope.ref.status == status


@pytest.mark.parametrize(
    ("grade", "status", "message"),
    [
        ("A", "watch", "grade must be C"),
        ("C", "ready", "status must be watch"),
    ],
)
def test_assessment_ref_rejects_score_mapping_mismatches(
    grade: str, status: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        AssessmentRefEnvelope.model_validate(
            _canonical_payload(score=72.0, grade=grade, status=status)
        )


def test_assessment_ref_rejects_embedded_workflow_organization_mismatch() -> None:
    payload = _canonical_payload()
    payload["ref"]["workflow_ref"]["ref"]["organization_id"] = "tenant_other"

    with pytest.raises(
        ValidationError,
        match="workflow_ref.ref.organization_id must equal ref.organization_id",
    ):
        AssessmentRefEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        (("ref",), "workflow_id", "workflow_demo_001"),
        (("ref",), "pillar_scores", [{"pillar": "oversight", "score": 72.0}]),
        (("ref", "workflow_ref", "ref"), "title", "Synthetic workflow"),
        (("ref",), "credentials", {"token": "synthetic-not-a-secret"}),
        (("ref",), "governance_approval", "approved"),
    ],
)
def test_assessment_ref_rejects_metadata_outside_canonical_allowlist(
    target: tuple[str, ...], field: str, value: object
) -> None:
    payload = _canonical_payload()
    destination = payload
    for component in target:
        destination = destination[component]
    destination[field] = value

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AssessmentRefEnvelope.model_validate(payload)


def test_canonical_assessment_ref_corpus_matches_readiness_models() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    for relative_path, expected_digest in lock["sha256"].items():
        artifact = (
            VENDORED_BINDING
            if relative_path == "bindings/python/assessment_ref.py"
            else VENDORED_ROOT / relative_path
        )
        actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert actual_digest == expected_digest, relative_path

    digest_manifest_path = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT / "artifact-digests.json"
    digest_manifest = json.loads(digest_manifest_path.read_text(encoding="utf-8"))
    assert digest_manifest["algorithm"] == "sha256"
    for relative_path, expected_digest in digest_manifest["artifacts"].items():
        if relative_path == "bindings/python/assessment_ref.py":
            artifact = VENDORED_BINDING
        elif relative_path.startswith(f"{CONTRACT_RELATIVE_ROOT.as_posix()}/"):
            artifact = VENDORED_ROOT / relative_path
        else:
            continue
        actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert actual_digest == expected_digest, relative_path

    contract_root = VENDORED_ROOT / CONTRACT_RELATIVE_ROOT
    schema = json.loads((contract_root / "schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    corpus_root = contract_root / "fixtures" / "corpus"
    index = json.loads((corpus_root / "index.json").read_text(encoding="utf-8"))
    for case in index["cases"]:
        payload = json.loads((corpus_root / case["file"]).read_text(encoding="utf-8"))
        schema_errors = list(schema_validator.iter_errors(payload))
        if case["expected_valid"]:
            assert schema_errors == [], case["name"]
            AssessmentRefEnvelope.model_validate(payload)
        else:
            with pytest.raises(ValidationError, match=".+"):
                AssessmentRefEnvelope.model_validate(payload)


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

    fresh_binding = fresh_root / "bindings" / "python" / "assessment_ref.py"
    assert VENDORED_BINDING.read_bytes() == fresh_binding.read_bytes()
