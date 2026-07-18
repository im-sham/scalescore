from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from scalescore.contracts.control_ref_consumer import ControlRefEnvelope
from scalescore.core.assessment import _workflow_evidence_from_control_refs

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = (
    REPO_ROOT
    / "contracts"
    / "vendor"
    / "proofhouse-contracts"
    / "contracts"
    / "control-ref"
    / "v0.1"
    / "fixtures"
    / "corpus"
)
CONTROL_REF_ADAPTER = TypeAdapter(ControlRefEnvelope)


def _canonical(fixture_name: str):
    payload = json.loads((CORPUS_ROOT / fixture_name).read_text(encoding="utf-8"))
    return CONTROL_REF_ADAPTER.validate_python(payload)


def test_canonical_states_feed_diagnostics_without_conferring_authority() -> None:
    envelope = _canonical("valid-linkage-verified.json")
    envelope.ref.implementation_state = "implemented"
    envelope.ref.control_key = "approval_gate"

    evidence = _workflow_evidence_from_control_refs([envelope])

    assert evidence.control_coverage is not None
    assert evidence.evidence_posture is not None
    assert evidence.control_coverage.approval_gate == "verified"
    assert evidence.evidence_posture.control_evidence_coverage_percent == 100.0
    assert evidence.evidence_posture.linked_artifacts is True
    assert evidence.evidence_posture.audit_trail_complete is False
    assert evidence.owner_confirmed is False
    assert evidence.approval_evidence_count == 0
    assert evidence.decision_log_count == 0


def test_planned_missing_synthetic_control_remains_missing() -> None:
    envelope = _canonical("valid-implementation-planned.json")
    envelope.ref.control_key = "approval_gate"
    envelope.ref.linkage_state = "missing"

    evidence = _workflow_evidence_from_control_refs([envelope])

    assert evidence.control_coverage is not None
    assert evidence.evidence_posture is not None
    assert evidence.control_coverage.approval_gate == "missing"
    assert evidence.evidence_posture.control_evidence_coverage_percent == 0.0
    assert evidence.evidence_posture.linked_artifacts is False


def test_legacy_authority_like_fields_are_never_scored() -> None:
    legacy = CONTROL_REF_ADAPTER.validate_python(
        {
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
    )

    evidence = _workflow_evidence_from_control_refs([legacy])

    assert evidence.control_coverage is not None
    assert evidence.evidence_posture is not None
    assert evidence.control_coverage.approval_gate == "missing"
    assert evidence.evidence_posture.control_evidence_coverage_percent == 0.0
    assert evidence.evidence_posture.audit_trail_complete is False
    assert evidence.evidence_posture.linked_artifacts is False
    assert evidence.owner_confirmed is False
    assert evidence.approval_evidence_count == 0
    assert evidence.decision_log_count == 0
