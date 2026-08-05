import base64
import json
import re
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from scalescore.api import main as api_main
from scalescore.api.main import app
from scalescore.config import settings
from scalescore.connectors.opsorchestra_connector import OpsOrchestraConnector
from scalescore.core.auth.external_oidc import get_external_oidc_auth_service
from scalescore.core.auth.opsorchestra import (
    OpsOrchestraAuthService,
    get_opsorchestra_auth_service,
)
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.core.rate_limit import RateLimitResult, get_rate_limiter
from scalescore.models.core import Organization, Team

client = TestClient(app)


class DenyAllRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        del key, limit, window_seconds
        self.calls += 1
        return RateLimitResult(allowed=False, retry_after_seconds=17)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    text_chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL):
        stream = match.group(1).strip()
        candidates = [stream]
        try:
            ascii85_stream = stream[:-2] if stream.endswith(b"~>") else stream
            candidates.append(base64.a85decode(ascii85_stream, adobe=False))
        except ValueError:
            pass
        for candidate in candidates:
            try:
                decoded = zlib.decompress(candidate)
            except zlib.error:
                if candidate is stream and len(candidates) > 1:
                    continue
                decoded = candidate
            text_chunks.append(decoded.decode("latin1", errors="ignore"))
            break
    return "\n".join(text_chunks)


def _login(email: str = "dev@example.com", password: str = "dev") -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def _auth_headers() -> dict[str, str]:
    token = _login()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _signup_and_auth_headers(*, tenant_id: str | None = None) -> dict[str, str]:
    email = f"user-{uuid4().hex[:8]}@example.com"
    tenant = tenant_id or f"tenant-{uuid4().hex[:8]}"
    signup_response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "strong-password",
            "tenant_id": tenant,
            "org_id": "org-async-tests",
            "roles": ["analyst"],
        },
    )
    assert signup_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "strong-password"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _write_dataset(tmp_path: Path) -> None:
    (tmp_path / "organizations.csv").write_text(
        "id,name,headcount_current,revenue_current,burn_rate_monthly,runway_months\n"
        "org_1,Acme,100,1000000,50000,18\n",
        encoding="utf-8",
    )
    (tmp_path / "teams.csv").write_text(
        "id,org_id,name,function,headcount_current,parent_team_id,manager_id\n"
        "team_1,org_1,Engineering,engineering,50,,mgr_1\n",
        encoding="utf-8",
    )
    (tmp_path / "systems.csv").write_text(
        "id,org_id,name,system_type,capacity_current,capacity_max,capacity_unit,is_critical,dependencies\n"
        "sys_1,org_1,CRM,crm,90,100,users,true,\n",
        encoding="utf-8",
    )
    (tmp_path / "vendors.csv").write_text(
        "id,org_id,name,vendor_type,annual_cost,is_critical,alternatives\n"
        "ven_1,org_1,AWS,saas,100000,true,Azure|GCP\n",
        encoding="utf-8",
    )
    (tmp_path / "facilities.csv").write_text(
        "id,org_id,name,facility_type,location,capacity_seats,capacity_used,lease_end_date\n"
        "fac_1,org_1,HQ,office,SF,100,90,2027-06-30\n",
        encoding="utf-8",
    )
    (tmp_path / "growth_signals.csv").write_text(
        "id,org_id,signal_type,title,target_date,magnitude,magnitude_type,confidence,affected_areas\n"
        "sig_1,org_1,headcount_plan,Scale,2026-12-31,100,percentage,0.8,engineering|operations\n",
        encoding="utf-8",
    )


def _upload_files(tmp_path: Path) -> dict[str, tuple[str, str, str]]:
    return {
        "organizations": (
            "organizations.csv",
            (tmp_path / "organizations.csv").read_text(),
            "text/csv",
        ),
        "teams": ("teams.csv", (tmp_path / "teams.csv").read_text(), "text/csv"),
        "systems": ("systems.csv", (tmp_path / "systems.csv").read_text(), "text/csv"),
        "vendors": ("vendors.csv", (tmp_path / "vendors.csv").read_text(), "text/csv"),
        "facilities": ("facilities.csv", (tmp_path / "facilities.csv").read_text(), "text/csv"),
        "growth_signals": (
            "growth_signals.csv",
            (tmp_path / "growth_signals.csv").read_text(),
            "text/csv",
        ),
    }


def _workflow_context_payload() -> dict[str, object]:
    return {
        "workflow_id": "wf_support_triage",
        "name": "Support Triage",
        "business_function": "customer_support",
        "owner": "Head of Support",
        "ai_role": "ticket triage and routing",
        "systems_touched": ["sys_1", "ven_1"],
        "human_escalation_path": ["support_lead", "ops_manager"],
        "control_requirements": ["approval_trace", "decision_logs"],
        "blast_radius": "medium",
        "description": "Classify and route inbound support tickets.",
        "fallback_mode": "manual queue review",
        "override_rights": ["support_manager"],
        "error_tolerance": "low",
        "reversibility": "tickets can be re-routed manually",
    }


def _workflow_ref_payload() -> dict[str, object]:
    return {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "WorkflowRef",
        "producer_capability": "workflow_context",
        "producer_system": "proofhouse-workflow-context",
        "canonical_owner": "workflow_context",
        "issued_at": "2026-04-25T12:00:00Z",
        "cache_policy": "summary_snapshot",
        "ref": {
            "ref_id": "workflow:dev-tenant:wf_support_triage",
            "ref_type": "workflow",
            "source_capability": "workflow_context",
            "organization_id": "dev-tenant",
            "environment_id": "production",
            "external_uri": "/api/workflows/wf_support_triage",
            "snapshot_id": "snapshot-support-triage-1",
            "version": "1.0",
            "created_at": "2026-04-25T11:55:00Z",
            "updated_at": "2026-04-25T11:59:00Z",
            "summary": "Support Triage (customer_support)",
            "workflow_id": "wf_support_triage",
            "title": "Support Triage",
            "subject_type": "customer_support",
            "subject_key": "support_triage",
            "owner": "Head of Support",
            "review_status": "approved",
        },
    }


def _canonical_workflow_ref_payload() -> dict[str, object]:
    return {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "WorkflowRef",
        "producer_capability": "workflow_context",
        "producer_system": "proofhouse-workflow-context",
        "canonical_owner": "workflow_context",
        "issued_at": "2026-07-30T12:00:00.123456Z",
        "cache_policy": "ref_only",
        "ref": {
            "ref_id": "workflow:wf_support_triage",
            "ref_type": "workflow",
            "source_capability": "workflow_context",
            "organization_id": "dev-tenant",
            "environment_id": "production",
            "external_uri": (
                "workflow-context://organizations/dev-tenant/environments/production/"
                "workflows/wf_support_triage/snapshots/snapshot-support-triage-1"
            ),
            "snapshot_id": "snapshot-support-triage-1",
            "version": "version-support-triage-7",
            "created_at": "2026-07-30T11:45:00.654321Z",
            "workflow_id": "wf_support_triage",
        },
    }


def _control_ref_payload(
    *,
    control_key: str = "approval_gate",
    implementation_state: str = "planned",
    linkage_state: str = "missing",
) -> dict[str, object]:
    return {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "ControlRef",
        "producer_capability": "workflow_context",
        "producer_system": "proofhouse-workflow-context",
        "canonical_owner": "workflow_context",
        "issued_at": "2026-04-25T12:00:30Z",
        "cache_policy": "summary_snapshot",
        "ref": {
            "ref_id": f"control:dev-tenant:wf_support_triage:{control_key}",
            "ref_type": "control",
            "source_capability": "workflow_context",
            "organization_id": "dev-tenant",
            "environment_id": "production",
            "external_uri": f"/api/workflows/wf_support_triage/controls/{control_key}",
            "snapshot_id": f"snapshot-support-triage-{control_key}",
            "created_at": "2026-04-25T11:58:00Z",
            "summary": ("Synthetic placeholder; no durable Workflow assignment record."),
            "control_assignment_id": f"assignment-{control_key}",
            "control_id": f"control-{control_key}",
            "control_key": control_key,
            "control_family": "support_triage",
            "workflow_id": "wf_support_triage",
            "workflow_ref": {
                "contract_version": "proofhouse-shared-contracts/v0.1",
                "contract_name": "WorkflowRef",
                "producer_capability": "workflow_context",
                "producer_system": "proofhouse-workflow-context",
                "canonical_owner": "workflow_context",
                "issued_at": "2026-04-25T12:00:00Z",
                "cache_policy": "summary_snapshot",
                "ref": {
                    "ref_id": "workflow:dev-tenant:wf_support_triage",
                    "ref_type": "workflow",
                    "source_capability": "workflow_context",
                    "organization_id": "dev-tenant",
                    "environment_id": "production",
                    "external_uri": "/api/workflows/wf_support_triage",
                    "snapshot_id": "snapshot-support-triage-1",
                    "workflow_id": "wf_support_triage",
                },
            },
            "implementation_state": implementation_state,
            "linkage_state": linkage_state,
        },
    }


def _legacy_control_ref_payload() -> dict[str, object]:
    payload = _control_ref_payload()
    ref = payload["ref"]
    assert isinstance(ref, dict)
    ref.pop("workflow_ref")
    ref.pop("implementation_state")
    ref.pop("linkage_state")
    ref.update(
        {
            "updated_at": "2026-04-25T12:00:00Z",
            "control_statement": "Historical compatibility statement.",
            "implementation_status": "implemented",
            "evidence_status": "complete",
            "owner": "Historical owner",
            "required_evidence_types": ["audit_log"],
        }
    )
    return payload


def _workflow_evidence_payload() -> dict[str, object]:
    return {
        "control_coverage": {
            "approval_gate": "verified",
            "decision_logging": "verified",
            "evidence_retention": "operating",
            "exception_handling": "operating",
            "periodic_review": "verified",
        },
        "evidence_posture": {
            "control_evidence_coverage_percent": 94.0,
            "freshest_evidence_age_days": 18,
            "audit_trail_complete": True,
            "linked_artifacts": True,
        },
        "owner_confirmed": True,
        "systems_verified": True,
        "escalation_tested": True,
        "fallback_tested": True,
        "override_reviewed": True,
        "approval_evidence_count": 4,
        "decision_log_count": 18,
        "rollback_tested": True,
    }


def _operational_learning_payload() -> dict[str, object]:
    return {
        "sop_reference_present": True,
        "sop_clarity_signal": 84.0,
        "outcome_spec_present": True,
        "outcome_observability_signal": 86.0,
        "repeatability_signal": 88.0,
        "review_path_present": True,
        "review_density_signal": 78.0,
        "redaction_manageability_signal": 82.0,
        "governance_dependency_state": {
            "rights_completeness": "complete",
            "provenance_completeness": "complete",
            "redaction_readiness": "complete",
            "residual_risk_band": "low",
        },
    }


def _document_operations_profile_payload() -> dict[str, object]:
    return {
        "fixture_id": "document_ops_regulated_review_v0",
        "subject_type": "document_packet",
        "subject_key": "claims-benefits-sample",
        "normal_case_id": "normal-packet",
        "normal_case_state": "closed_with_evidence",
        "normal_case_closed_with_evidence": True,
        "exception_case_id": "exception-packet",
        "exception_case_state": "requires_compliance_signoff",
        "exception_case_escalated": True,
        "exception_requires_compliance_signoff": True,
        "redaction_review_required_before_internal_eval": True,
        "sop_refs_present": True,
        "outcome_refs_present": True,
        "required_document_rules_present": True,
        "evidence_refs_present": True,
        "owner_confirmed": True,
        "systems_verified": True,
        "review_sla_defined": True,
        "weekly_packet_volume": 55.0,
        "reviewed_case_count": 42,
        "source_evidence_ref_count": 12,
        "control_evidence_coverage_percent": 96.0,
        "freshest_evidence_age_days": 6,
        "governance_dependency_state": {
            "rights_completeness": "complete",
            "provenance_completeness": "complete",
            "redaction_readiness": "complete",
            "residual_risk_band": "low",
        },
    }


def _claims_profile_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "profile_id": "claims-hybrid-high-dollar-review-v0",
        "evidence_class_ids_present": [
            "claim_packet",
            "claim_line",
            "invoice_provider_bill",
            "eob_remittance_evidence",
            "policy_plan_document",
            "contract_rate_source",
            "specialist_review_note",
            "downstream_export_record",
            "savings_recognition_record",
            "audit_packet",
        ],
        "phi_boundary_review_state": "reviewed",
        "redaction_review_state": "reviewed",
        "rate_source_review_state": "reviewed",
        "downstream_consistency_state": "ready",
        "downstream_action_approval_state": "approved",
        "savings_recognition_state": "approved",
        "governance_claims_control_state": "ready",
        "source_readiness_state": "ready",
    }
    payload.update(overrides)
    return payload


def _claims_document_operations_workflow_context_payload() -> dict[str, object]:
    return {
        "workflow_id": "document_ops_regulated_review_v0",
        "name": "Claims and Benefits Packet Review",
        "business_function": "document_operations",
        "owner": "Document Operations Lead",
        "ai_role": "Classify packets, extract fields, and route exception cases",
        "systems_touched": ["intake_queue", "document_store", "review_console"],
        "human_escalation_path": [
            "Document Operations Lead",
            "Compliance Reviewer",
        ],
        "control_requirements": [
            "required document checks",
            "review-required decision logging",
            "evidence retention",
        ],
        "blast_radius": "high",
        "fallback_mode": "Manual packet review with compliance escalation",
        "override_rights": ["Document Operations Lead", "Compliance Reviewer"],
        "error_tolerance": "Low tolerance for unsupported determinations",
        "reversibility": "Reviewer decisions can be corrected before packaging.",
    }


def _mila_workflow_assessment_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "org_id": "dev-tenant",
        "org_name": "Default Tenant",
        "workflow_context": _workflow_context_payload(),
        "workflow_ref": _workflow_ref_payload(),
        "workflow_evidence": _workflow_evidence_payload(),
        "operational_learning_inputs": _operational_learning_payload(),
        "baseline_operational_score": 82.0,
        "source_system": "mila",
        "source_workflow_type": "runbook_playbook",
        "source_runbook_id": "runbook-123",
        "source_playbook_id": "playbook-456",
        "source_findings": [
            "Runbook readiness is 90% (at_risk).",
            "Playbook definition coverage is 87.5%.",
        ],
        "notes": "Submitted from Mila direct workflow context.",
    }
    payload.update(overrides)
    return payload


def _mila_workflow_assessment_payload_for_org(org_id: str) -> dict[str, object]:
    workflow_ref = _workflow_ref_payload()
    ref = workflow_ref["ref"]
    assert isinstance(ref, dict)
    ref["organization_id"] = org_id
    return _mila_workflow_assessment_payload(org_id=org_id, workflow_ref=workflow_ref)


def _compact_mila_workflow_assessment_payload_for_org(org_id: str) -> dict[str, object]:
    workflow_ref = _canonical_workflow_ref_payload()
    ref = workflow_ref["ref"]
    assert isinstance(ref, dict)
    ref["organization_id"] = org_id
    ref["external_uri"] = (
        f"workflow-context://organizations/{org_id}/environments/production/"
        "workflows/wf_support_triage/snapshots/snapshot-support-triage-1"
    )
    return _mila_workflow_assessment_payload(org_id=org_id, workflow_ref=workflow_ref)


def _issue_opsorchestra_token(
    *,
    private_key: rsa.RSAPrivateKey,
    tenant_id: str = "ops-tenant",
    roles: list[str] | None = None,
) -> str:
    roles = roles or ["admin"]
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": tenant_id,
            "email": "ops-user@example.com",
            "roles": roles,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )


def _issue_external_oidc_token(
    *,
    private_key: rsa.RSAPrivateKey,
    tenant_id: str = "oidc-tenant",
    roles: list[str] | None = None,
) -> str:
    roles = roles or ["admin"]
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "oidc-user-1",
            "tid": tenant_id,
            "email": "oidc-user@example.com",
            "groups": roles,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "https://idp.example.com/",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )


def test_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_assessment_requires_auth(tmp_path: Path) -> None:
    response = client.post("/api/v1/assessments", params={"dataset_path": str(tmp_path)})

    assert response.status_code == 401


def test_create_assessment(tmp_path: Path) -> None:
    _write_dataset(tmp_path)

    response = client.post(
        "/api/v1/assessments",
        params={"dataset_path": str(tmp_path)},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["org_id"] == "org_1"
    assert payload["overall_score"] >= 0
    assert payload["executive_summary"]
    assert "overall score" in payload["executive_summary"].lower()

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["report_id"] == payload["report_id"]


def test_create_workflow_assessment(tmp_path: Path) -> None:
    _write_dataset(tmp_path)

    response = client.post(
        "/api/v1/assessments/workflow",
        json={
            "dataset_path": str(tmp_path),
            "workflow_context": _workflow_context_payload(),
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_mode"] == "workflow"
    assert payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    assert payload["workflow_readiness_score"] is not None
    assert payload["workflow_pillar_scores"]
    assert payload["top_trust_gaps"]


def test_create_mila_workflow_assessment_legacy_endpoint_returns_full_report() -> None:
    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(),
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_mode"] == "workflow"
    assert payload["org_id"] == "dev-tenant"
    assert payload["org_name"] == "Default Tenant"
    assert payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    assert payload["workflow_ref"]["contract_name"] == "WorkflowRef"
    assert payload["workflow_ref"]["ref"]["snapshot_id"] == "snapshot-support-triage-1"
    assert payload["assessment_ref"]["contract_name"] == "AssessmentRef"
    assert payload["assessment_ref"]["producer_capability"] == "readiness"
    assert payload["assessment_ref"]["ref"]["assessment_id"] == payload["report_id"]
    assessment_summary = payload["assessment_ref"]["ref"]
    assert assessment_summary["external_uri"] == f"/api/v1/assessments/{payload['report_id']}"
    assert assessment_summary["workflow_ref"]["ref"]["ref_id"] == (
        "workflow:dev-tenant:wf_support_triage"
    )
    assert set(assessment_summary) == {
        "ref_id",
        "ref_type",
        "source_capability",
        "organization_id",
        "environment_id",
        "external_uri",
        "snapshot_id",
        "version",
        "created_at",
        "summary",
        "assessment_id",
        "workflow_ref",
        "assessment_type",
        "score",
        "grade",
        "status",
        "top_blockers",
        "top_reasons",
    }
    assert set(assessment_summary["workflow_ref"]["ref"]) == {
        "ref_id",
        "ref_type",
        "source_capability",
        "organization_id",
        "environment_id",
        "external_uri",
        "snapshot_id",
        "version",
    }
    assert payload["workflow_readiness_score"] is not None
    assert payload["overall_score"] == payload["workflow_readiness_score"]
    assert payload["operational_learning_suitability"] is not None
    assert payload["operational_learning_suitability"]["status"] == "training_candidate"
    assert (
        payload["operational_learning_suitability"]["eval_suitability"]["status"] == "eval_suitable"
    )
    assert (
        payload["operational_learning_suitability"]["internal_training_candidacy"]["status"]
        == "training_candidate"
    )
    assert "Runbook readiness is 90% (at_risk)." in payload["key_findings"]
    control_pillar = next(
        pillar
        for pillar in payload["workflow_pillar_scores"]
        if pillar["pillar"] == "control_and_evidence_readiness"
    )
    assert any(
        "verified by source evidence" in strength for strength in control_pillar["strengths"]
    )
    assert (
        "Source evidence coverage for mapped workflow controls is high."
        in control_pillar["rationale"]
    )

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    stored_payload = get_response.json()
    assert stored_payload["report_id"] == payload["report_id"]
    assert stored_payload["workflow_ref"]["ref"]["snapshot_id"] == "snapshot-support-triage-1"
    assert stored_payload["assessment_ref"]["ref"]["assessment_id"] == payload["report_id"]


def test_legacy_workflow_route_rejects_canonical_shape_without_persistence() -> None:
    headers = _auth_headers()
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    request_payload = _mila_workflow_assessment_payload(
        workflow_ref=_canonical_workflow_ref_payload()
    )

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=request_payload,
        headers=headers,
    )

    assert response.status_code == 422
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == len(before_response.json())


def test_create_mila_workflow_assessment_ref_returns_exact_compact_envelope() -> None:
    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=_compact_mila_workflow_assessment_payload_for_org("dev-tenant"),
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "contract_version",
        "contract_name",
        "producer_capability",
        "producer_system",
        "canonical_owner",
        "issued_at",
        "cache_policy",
        "ref",
    }
    assert set(payload["ref"]) == {
        "ref_id",
        "ref_type",
        "source_capability",
        "organization_id",
        "environment_id",
        "external_uri",
        "snapshot_id",
        "version",
        "created_at",
        "summary",
        "assessment_id",
        "workflow_ref",
        "assessment_type",
        "score",
        "grade",
        "status",
        "top_blockers",
        "top_reasons",
    }
    assert set(payload["ref"]["workflow_ref"]) == {
        "contract_version",
        "contract_name",
        "producer_capability",
        "producer_system",
        "canonical_owner",
        "issued_at",
        "cache_policy",
        "ref",
    }
    assert set(payload["ref"]["workflow_ref"]["ref"]) == {
        "ref_id",
        "ref_type",
        "source_capability",
        "organization_id",
        "environment_id",
        "external_uri",
        "snapshot_id",
        "version",
    }
    workflow_alignment = payload["ref"]["workflow_ref"]
    assert workflow_alignment["issued_at"] == "2026-07-30T12:00:00.123456Z"
    assert workflow_alignment["cache_policy"] == "summary_snapshot"
    assert workflow_alignment["ref"]["ref_id"] == "workflow:wf_support_triage"
    assert workflow_alignment["ref"]["snapshot_id"] == "snapshot-support-triage-1"
    assert workflow_alignment["ref"]["version"] == "version-support-triage-7"
    assert payload["ref"]["assessment_type"] == "workflow_readiness"
    assert "created_at" not in workflow_alignment["ref"]
    report_response = client.get(
        f"/api/v1/assessments/{payload['ref']['assessment_id']}",
        headers=_auth_headers(),
    )
    assert report_response.status_code == 200
    stored_workflow_ref = report_response.json()["workflow_ref"]
    assert stored_workflow_ref == _canonical_workflow_ref_payload()
    prohibited_fields = {
        "report_id",
        "assessment_mode",
        "workflow_context",
        "workflow_pillar_scores",
        "top_trust_gaps",
        "prioritized_remediation_actions",
        "operational_learning_suitability",
        "source_findings",
        "notes",
    }
    assert prohibited_fields.isdisjoint(payload)
    assert prohibited_fields.isdisjoint(payload["ref"])


def test_create_mila_workflow_assessment_ref_emits_operational_learning_suitability() -> None:
    request_payload = _compact_mila_workflow_assessment_payload_for_org("dev-tenant")
    request_payload["assessment_type"] = "operational_learning_suitability"

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assessment_ref = response.json()
    assessment = assessment_ref["ref"]
    assert assessment["assessment_type"] == "operational_learning_suitability"
    assert assessment["workflow_ref"]["ref"] == {
        "ref_id": "workflow:wf_support_triage",
        "ref_type": "workflow",
        "source_capability": "workflow_context",
        "organization_id": "dev-tenant",
        "environment_id": "production",
        "external_uri": (
            "workflow-context://organizations/dev-tenant/environments/production/"
            "workflows/wf_support_triage/snapshots/snapshot-support-triage-1"
        ),
        "snapshot_id": "snapshot-support-triage-1",
        "version": "version-support-triage-7",
    }
    assert assessment["summary"].startswith(
        "Operational Learning eval suitability for Support Triage:"
    )
    assert "operational_learning_suitability" not in assessment
    assert "workflow_pillar_scores" not in assessment

    report_response = client.get(
        f"/api/v1/assessments/{assessment['assessment_id']}",
        headers=_auth_headers(),
    )
    assert report_response.status_code == 200
    stored_report = report_response.json()
    suitability = stored_report["operational_learning_suitability"]
    assert suitability is not None
    assert assessment["score"] == suitability["eval_suitability"]["score"]
    assert assessment["top_blockers"] == suitability["top_blockers"][:5]
    assert assessment["top_reasons"] == suitability["top_reasons"][:5]
    assert stored_report["assessment_ref"] == assessment_ref


def test_create_mila_workflow_assessment_ref_preserves_operational_learning_hard_block() -> None:
    operational_learning_inputs = _operational_learning_payload()
    operational_learning_inputs.pop("governance_dependency_state")
    request_payload = _compact_mila_workflow_assessment_payload_for_org("dev-tenant")
    request_payload.update(
        {
            "assessment_type": "operational_learning_suitability",
            "operational_learning_inputs": operational_learning_inputs,
        }
    )

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assessment = response.json()["ref"]
    assert assessment["assessment_type"] == "operational_learning_suitability"
    assert assessment["score"] == 49.0
    assert assessment["grade"] == "F"
    assert assessment["status"] == "blocked"
    assert any(
        "Governance dependency state is missing" in blocker
        for blocker in assessment["top_blockers"]
    )
    assert "hard blocker gate applied" in assessment["summary"]


def test_create_mila_workflow_assessment_ref_requires_operational_learning_assessment_before_scoring(
    monkeypatch,
) -> None:
    headers = _auth_headers()
    request_payload = _compact_mila_workflow_assessment_payload_for_org("dev-tenant")
    request_payload["assessment_type"] = "operational_learning_suitability"
    request_payload.pop("operational_learning_inputs")
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())

    def fail_scoring(**kwargs):
        del kwargs
        pytest.fail("missing Operational Learning inputs reached scoring")

    def fail_audit(**kwargs):
        del kwargs
        pytest.fail("missing Operational Learning inputs reached audit")

    monkeypatch.setattr(api_main, "run_workflow_assessment", fail_scoring)
    monkeypatch.setattr(api_main, "audit_assessment_created", fail_audit)

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "OPERATIONAL_LEARNING_NOT_ASSESSED"
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


def test_create_mila_workflow_assessment_ref_rejects_unknown_assessment_type_before_scoring(
    monkeypatch,
) -> None:
    request_payload = _compact_mila_workflow_assessment_payload_for_org("dev-tenant")
    request_payload["assessment_type"] = "unknown_assessment"

    def fail_scoring(**kwargs):
        del kwargs
        pytest.fail("unknown assessment type reached scoring")

    monkeypatch.setattr(api_main, "run_workflow_assessment", fail_scoring)

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=_auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCALE_1005"


@pytest.mark.parametrize("workflow_ref_value", ["missing", "null"])
def test_create_mila_workflow_assessment_ref_requires_workflow_ref_before_persistence(
    workflow_ref_value: str,
) -> None:
    headers = _signup_and_auth_headers()
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())
    request_payload = _mila_workflow_assessment_payload()
    if workflow_ref_value == "missing":
        request_payload.pop("workflow_ref")
    else:
        request_payload["workflow_ref"] = None

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "WORKFLOW_REF_REQUIRED"
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


@pytest.mark.parametrize(
    ("invalid_case", "expected_status"),
    [
        ("noncanonical_cache_policy", 422),
        ("missing_canonical_owner", 422),
        ("malformed_issued_at", 422),
        ("timezone_less_issued_at", 422),
        ("malformed_created_at", 422),
        ("timezone_less_created_at", 422),
        ("missing_external_uri", 422),
        ("empty_external_uri", 422),
        ("missing_snapshot_id", 422),
        ("missing_environment_id", 422),
        ("empty_environment_id", 422),
        ("missing_version", 422),
        ("unknown_envelope_property", 422),
        ("unknown_nested_ref_property", 422),
        ("unknown_top_level_request_property", 422),
        ("payload_ref_organization_mismatch", 422),
        ("authenticated_tenant_mismatch", 403),
        ("legacy_shape", 422),
        ("forbidden_updated_at", 422),
        ("forbidden_summary", 422),
        ("forbidden_title", 422),
        ("explicit_null_legacy_field", 422),
        ("placeholder_organization", 422),
        ("mutable_snapshot", 422),
        ("workflow_ref_id_mismatch", 422),
        ("workflow_context_mismatch", 422),
        ("environment_mismatch", 422),
    ],
)
def test_create_mila_workflow_assessment_ref_rejects_noncanonical_input_without_side_effects(
    invalid_case: str,
    expected_status: int,
    monkeypatch,
) -> None:
    tenant_id = "dev-tenant"
    headers = _auth_headers()
    request_payload = _compact_mila_workflow_assessment_payload_for_org(tenant_id)
    workflow_ref = request_payload["workflow_ref"]
    assert isinstance(workflow_ref, dict)
    ref = workflow_ref["ref"]
    assert isinstance(ref, dict)

    if invalid_case == "noncanonical_cache_policy":
        workflow_ref["cache_policy"] = "summary_snapshot"
    elif invalid_case == "missing_canonical_owner":
        workflow_ref.pop("canonical_owner")
    elif invalid_case == "malformed_issued_at":
        workflow_ref["issued_at"] = "not-a-timestamp"
    elif invalid_case == "timezone_less_issued_at":
        workflow_ref["issued_at"] = "2026-07-18T07:17:27"
    elif invalid_case == "malformed_created_at":
        ref["created_at"] = "not-a-timestamp"
    elif invalid_case == "timezone_less_created_at":
        ref["created_at"] = "2026-07-18T07:17:27"
    elif invalid_case == "missing_external_uri":
        ref.pop("external_uri")
    elif invalid_case == "empty_external_uri":
        ref["external_uri"] = ""
    elif invalid_case == "missing_environment_id":
        ref.pop("environment_id")
    elif invalid_case == "empty_environment_id":
        ref["environment_id"] = ""
    elif invalid_case == "missing_snapshot_id":
        ref.pop("snapshot_id")
    elif invalid_case == "missing_version":
        ref.pop("version")
    elif invalid_case == "unknown_envelope_property":
        workflow_ref["unexpected"] = "rejected"
    elif invalid_case == "unknown_nested_ref_property":
        ref["unexpected"] = "rejected"
    elif invalid_case == "unknown_top_level_request_property":
        request_payload["unexpected"] = "rejected"
    elif invalid_case == "payload_ref_organization_mismatch":
        ref["organization_id"] = f"{tenant_id}-other"
    elif invalid_case == "authenticated_tenant_mismatch":
        request_payload = _compact_mila_workflow_assessment_payload_for_org(f"{tenant_id}-other")
    elif invalid_case == "legacy_shape":
        request_payload["workflow_ref"] = _workflow_ref_payload()
    elif invalid_case == "forbidden_updated_at":
        ref["updated_at"] = "2026-07-30T11:50:00Z"
    elif invalid_case == "forbidden_summary":
        ref["summary"] = "mutable workflow summary"
    elif invalid_case == "forbidden_title":
        ref["title"] = "Mutable workflow title"
    elif invalid_case == "explicit_null_legacy_field":
        ref["owner"] = None
    elif invalid_case == "placeholder_organization":
        ref["organization_id"] = "default"
    elif invalid_case == "mutable_snapshot":
        ref["snapshot_id"] = "latest"
    elif invalid_case == "workflow_ref_id_mismatch":
        ref["ref_id"] = "workflow:other_workflow"
    elif invalid_case == "workflow_context_mismatch":
        workflow_context = request_payload["workflow_context"]
        assert isinstance(workflow_context, dict)
        workflow_context["workflow_id"] = "other_workflow"
    elif invalid_case == "environment_mismatch":
        control_ref = _control_ref_payload()
        control = control_ref["ref"]
        assert isinstance(control, dict)
        control["organization_id"] = tenant_id
        control["environment_id"] = "test"
        owning_envelope = control["workflow_ref"]
        assert isinstance(owning_envelope, dict)
        owning_workflow = owning_envelope["ref"]
        assert isinstance(owning_workflow, dict)
        owning_workflow["organization_id"] = tenant_id
        request_payload["control_refs"] = [control_ref]
    else:
        raise AssertionError(f"Unhandled invalid case: {invalid_case}")

    scoring_calls = 0
    audit_calls = 0

    def fail_scoring(**kwargs):
        nonlocal scoring_calls
        del kwargs
        scoring_calls += 1
        pytest.fail("invalid compact request reached scoring")

    def fail_audit(**kwargs):
        nonlocal audit_calls
        del kwargs
        audit_calls += 1
        pytest.fail("invalid compact request reached audit")

    monkeypatch.setattr(api_main, "run_workflow_assessment", fail_scoring)
    monkeypatch.setattr(api_main, "audit_assessment_created", fail_audit)
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())

    response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=request_payload,
        headers=headers,
    )

    assert response.status_code == expected_status
    assert scoring_calls == 0
    assert audit_calls == 0
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


def test_create_mila_workflow_assessment_ref_persists_tenant_scoped_full_report() -> None:
    tenant_a_id = f"tenant-a-{uuid4().hex[:8]}"
    tenant_b_id = f"tenant-b-{uuid4().hex[:8]}"
    tenant_a_headers = _signup_and_auth_headers(tenant_id=tenant_a_id)
    tenant_b_headers = _signup_and_auth_headers(tenant_id=tenant_b_id)

    create_response = client.post(
        "/api/v1/assessments/mila/workflow/assessment-ref",
        json=_compact_mila_workflow_assessment_payload_for_org(tenant_a_id),
        headers=tenant_a_headers,
    )

    assert create_response.status_code == 200
    assessment_ref = create_response.json()
    assessment_id = assessment_ref["ref"]["assessment_id"]
    owner_response = client.get(
        f"/api/v1/assessments/{assessment_id}",
        headers=tenant_a_headers,
    )
    cross_tenant_response = client.get(
        f"/api/v1/assessments/{assessment_id}",
        headers=tenant_b_headers,
    )

    assert owner_response.status_code == 200
    stored_report = owner_response.json()
    assert stored_report["report_id"] == assessment_id
    assert stored_report["assessment_ref"] == assessment_ref
    assert stored_report["workflow_pillar_scores"]
    assert stored_report["operational_learning_suitability"] is not None
    assert cross_tenant_response.status_code == 404
    assert cross_tenant_response.json()["error"]["code"] == "SCALE_2000"


def test_assessment_dereference_isolated_by_authenticated_tenant() -> None:
    tenant_a_id = f"tenant-a-{uuid4().hex[:8]}"
    tenant_a_headers = _signup_and_auth_headers(tenant_id=tenant_a_id)
    tenant_b_headers = _signup_and_auth_headers(tenant_id=f"tenant-b-{uuid4().hex[:8]}")
    create_response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload_for_org(tenant_a_id),
        headers=tenant_a_headers,
    )
    assert create_response.status_code == 200
    assessment_id = create_response.json()["report_id"]

    owner_response = client.get(
        f"/api/v1/assessments/{assessment_id}",
        headers=tenant_a_headers,
    )
    cross_tenant_response = client.get(
        f"/api/v1/assessments/{assessment_id}",
        headers=tenant_b_headers,
    )

    assert owner_response.status_code == 200
    assert cross_tenant_response.status_code == 404
    assert cross_tenant_response.json()["error"]["code"] == "SCALE_2000"


def test_create_mila_workflow_assessment_preserves_diagnostic_control_refs() -> None:
    control_refs = [
        _control_ref_payload(control_key="approval_gate"),
        _control_ref_payload(control_key="decision_logging"),
        _control_ref_payload(control_key="evidence_retention"),
        _control_ref_payload(control_key="exception_handling"),
        _control_ref_payload(control_key="periodic_review"),
    ]
    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            workflow_evidence=None,
            control_refs=control_refs,
        ),
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["control_refs"] == control_refs
    assert "version" not in payload["control_refs"][0]["ref"]
    assert "version" not in payload["control_refs"][0]["ref"]["workflow_ref"]["ref"]
    control_pillar = next(
        pillar
        for pillar in payload["workflow_pillar_scores"]
        if pillar["pillar"] == "control_and_evidence_readiness"
    )
    assert not any(
        "verified by source evidence" in strength for strength in control_pillar["strengths"]
    )
    assert (
        "Source evidence coverage for mapped workflow controls is high."
        not in control_pillar["rationale"]
    )

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["control_refs"] == control_refs


def test_exact_legacy_control_ref_remains_exact_through_api_readback() -> None:
    legacy_control_ref = _legacy_control_ref_payload()
    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            workflow_evidence=None,
            control_refs=[legacy_control_ref],
        ),
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["control_refs"] == [legacy_control_ref]
    assert "implementation_state" not in payload["control_refs"][0]["ref"]
    assert "workflow_ref" not in payload["control_refs"][0]["ref"]

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["control_refs"] == [legacy_control_ref]


def test_control_ref_tenant_mismatch_fails_before_persistence() -> None:
    headers = _signup_and_auth_headers()
    before = client.get("/api/v1/assessments", headers=headers)
    control_ref = _control_ref_payload()
    ref = control_ref["ref"]
    assert isinstance(ref, dict)
    ref["organization_id"] = "tenant_other"
    owning_envelope = ref["workflow_ref"]
    assert isinstance(owning_envelope, dict)
    owning_ref = owning_envelope["ref"]
    assert isinstance(owning_ref, dict)
    owning_ref["organization_id"] = "tenant_other"

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(control_refs=[control_ref]),
        headers=headers,
    )
    after = client.get("/api/v1/assessments", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_SCOPE_MISMATCH"
    assert len(after.json()) == len(before.json())


def test_control_ref_workflow_mismatch_fails_before_scoring() -> None:
    control_ref = _control_ref_payload()
    ref = control_ref["ref"]
    assert isinstance(ref, dict)
    ref["workflow_id"] = "wf_other"
    owning_envelope = ref["workflow_ref"]
    assert isinstance(owning_envelope, dict)
    owning_ref = owning_envelope["ref"]
    assert isinstance(owning_ref, dict)
    owning_ref["workflow_id"] = "wf_other"

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(control_refs=[control_ref]),
        headers=_auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CONTROL_WORKFLOW_MISMATCH"


def test_control_ref_environment_mismatch_fails_before_scoring() -> None:
    control_ref = _control_ref_payload()
    ref = control_ref["ref"]
    assert isinstance(ref, dict)
    ref["environment_id"] = "staging"
    owning_envelope = ref["workflow_ref"]
    assert isinstance(owning_envelope, dict)
    owning_ref = owning_envelope["ref"]
    assert isinstance(owning_ref, dict)
    owning_ref["environment_id"] = "staging"

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(control_refs=[control_ref]),
        headers=_auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CONTROL_ENVIRONMENT_MISMATCH"


def test_control_ref_explicit_null_pin_is_rejected_at_request_boundary() -> None:
    control_ref = _control_ref_payload()
    ref = control_ref["ref"]
    assert isinstance(ref, dict)
    ref["version"] = None

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(control_refs=[control_ref]),
        headers=_auth_headers(),
    )

    assert response.status_code == 422


def test_create_mila_workflow_assessment_rejects_source_findings_raw_payload_before_persistence() -> (
    None
):
    headers = _auth_headers()
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            source_findings=['raw_payload: {"document_text": "REJECTED_RAW_SOURCE_SENTINEL"}'],
        ),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SUMMARY_ONLY_INPUT_REQUIRED"
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


def test_create_mila_workflow_assessment_rejects_notes_raw_payload_before_persistence() -> None:
    headers = _auth_headers()
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            notes='{"claim_payload": {"ssn": "REJECTED_RAW_NOTE_SENTINEL"}}',
        ),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SUMMARY_ONLY_INPUT_REQUIRED"
    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


def test_create_mila_workflow_assessment_rejects_document_operations_profile_raw_fields_before_persistence() -> (
    None
):
    headers = _auth_headers()
    before_response = client.get("/api/v1/assessments", headers=headers)
    assert before_response.status_code == 200
    before_count = len(before_response.json())
    raw_profile_value = '{"claim_payload": {"member_id": "REJECTED_PROFILE_SENTINEL"}}'

    profile_cases = [
        (("fixture_id",), "document_operations_profile.fixture_id"),
        (("subject_type",), "document_operations_profile.subject_type"),
        (("subject_key",), "document_operations_profile.subject_key"),
        (("normal_case_id",), "document_operations_profile.normal_case_id"),
        (("normal_case_state",), "document_operations_profile.normal_case_state"),
        (("exception_case_id",), "document_operations_profile.exception_case_id"),
        (("exception_case_state",), "document_operations_profile.exception_case_state"),
        (
            ("claims_profile", "profile_id"),
            "document_operations_profile.claims_profile.profile_id",
        ),
    ]

    for path, expected_field in profile_cases:
        document_operations_profile = _document_operations_profile_payload()
        document_operations_profile["claims_profile"] = _claims_profile_payload()
        if path == ("claims_profile", "profile_id"):
            claims_profile = document_operations_profile["claims_profile"]
            assert isinstance(claims_profile, dict)
            claims_profile["profile_id"] = raw_profile_value
        else:
            document_operations_profile[path[0]] = raw_profile_value

        response = client.post(
            "/api/v1/assessments/mila/workflow",
            json=_mila_workflow_assessment_payload(
                workflow_context=_claims_document_operations_workflow_context_payload(),
                workflow_ref=None,
                document_operations_profile=document_operations_profile,
            ),
            headers=headers,
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "SUMMARY_ONLY_INPUT_REQUIRED"
        assert expected_field in detail["fields"]

    after_response = client.get("/api/v1/assessments", headers=headers)
    assert after_response.status_code == 200
    assert len(after_response.json()) == before_count


def test_mila_workflow_pdf_export_remains_summary_only_after_guarded_rejection() -> None:
    headers = _auth_headers()
    rejected_source_text = "REJECTED_RAW_SOURCE_SENTINEL"
    rejected_note_text = "REJECTED_RAW_NOTE_SENTINEL"

    rejected_response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            source_findings=[f'payment_payload: {{"document_text": "{rejected_source_text}"}}'],
            notes=f"member_id: {rejected_note_text}",
        ),
        headers=headers,
    )
    assert rejected_response.status_code == 422

    accepted_response = client.post(
        "/api/v1/assessments/mila/workflow",
        json=_mila_workflow_assessment_payload(
            source_findings=[
                "Workflow evidence coverage is summarized from 4 approval refs.",
                "Synthetic fixture packet count: 12.",
            ],
            notes="Summary-only review note: escalation path and owner refs confirmed.",
        ),
        headers=headers,
    )
    assert accepted_response.status_code == 200
    payload = accepted_response.json()

    export_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}/export/pdf",
        headers=headers,
    )
    assert export_response.status_code == 200
    assert export_response.content.startswith(b"%PDF")
    pdf_text = _extract_pdf_text(export_response.content)
    assert "Workflow evidence coverage is summarized" in pdf_text
    assert rejected_source_text not in pdf_text
    assert rejected_note_text not in pdf_text


def test_create_mila_workflow_assessment_accepts_document_operations_profile() -> None:
    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json={
            "org_id": "dev-tenant",
            "org_name": "Default Tenant",
            "workflow_context": {
                "workflow_id": "document_ops_regulated_review_v0",
                "name": "Claims and Benefits Packet Review",
                "business_function": "document_operations",
                "owner": "Document Operations Lead",
                "ai_role": "Classify packets, extract fields, and route exception cases",
                "systems_touched": ["intake_queue", "document_store", "review_console"],
                "human_escalation_path": [
                    "Document Operations Lead",
                    "Compliance Reviewer",
                ],
                "control_requirements": [
                    "required document checks",
                    "review-required decision logging",
                    "evidence retention",
                ],
                "blast_radius": "high",
                "fallback_mode": "Manual packet review with compliance escalation",
                "override_rights": ["Document Operations Lead", "Compliance Reviewer"],
                "error_tolerance": "Low tolerance for unsupported determinations",
                "reversibility": "Reviewer decisions can be corrected before packaging.",
            },
            "workflow_ref": {
                **_workflow_ref_payload(),
                "ref": {
                    **_workflow_ref_payload()["ref"],
                    "ref_id": "workflow:dev-tenant:document_ops_regulated_review_v0",
                    "workflow_id": "document_ops_regulated_review_v0",
                    "title": "Claims and Benefits Packet Review",
                    "subject_type": "document_packet",
                    "subject_key": "claims-benefits-sample",
                    "owner": "Document Operations Lead",
                    "review_status": "human_reviewed",
                },
            },
            "document_operations_profile": _document_operations_profile_payload(),
            "baseline_operational_score": 84.0,
            "source_system": "mila",
            "source_workflow_type": "document_operations_fixture",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_context"]["workflow_id"] == "document_ops_regulated_review_v0"
    assert payload["workflow_readiness_score"] is not None
    assert len(payload["workflow_pillar_scores"]) == 5
    assert payload["assessment_ref"]["contract_version"] == "proofhouse-shared-contracts/v0.1"
    assert payload["assessment_ref"]["ref"]["workflow_ref"]["ref"]["ref_id"] == (
        "workflow:dev-tenant:document_ops_regulated_review_v0"
    )
    assert payload["workflow_ref"]["ref"]["subject_type"] == "document_packet"
    assert payload["operational_learning_suitability"]["status"] == "training_candidate"
    assert payload["claims_suitability"] is None
    assert any("document_ops_regulated_review_v0" in finding for finding in payload["key_findings"])


def test_create_mila_workflow_assessment_accepts_claims_profile_through_document_operations_profile() -> (
    None
):
    document_operations_profile = _document_operations_profile_payload()
    document_operations_profile["claims_profile"] = _claims_profile_payload()

    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json={
            "org_id": "dev-tenant",
            "org_name": "Default Tenant",
            "workflow_context": {
                "workflow_id": "document_ops_regulated_review_v0",
                "name": "Claims and Benefits Packet Review",
                "business_function": "document_operations",
                "owner": "Document Operations Lead",
                "ai_role": "Classify packets, extract fields, and route exception cases",
                "systems_touched": ["intake_queue", "document_store", "review_console"],
                "human_escalation_path": [
                    "Document Operations Lead",
                    "Compliance Reviewer",
                ],
                "control_requirements": [
                    "required document checks",
                    "review-required decision logging",
                    "evidence retention",
                ],
                "blast_radius": "high",
                "fallback_mode": "Manual packet review with compliance escalation",
                "override_rights": ["Document Operations Lead", "Compliance Reviewer"],
                "error_tolerance": "Low tolerance for unsupported determinations",
                "reversibility": "Reviewer decisions can be corrected before packaging.",
            },
            "document_operations_profile": document_operations_profile,
            "baseline_operational_score": 84.0,
            "source_system": "mila",
            "source_workflow_type": "document_operations_fixture",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["claims_suitability"]["profile_id"] == "claims-hybrid-high-dollar-review-v0"
    assert payload["claims_suitability"]["status"] == "eval_suitable"
    assert payload["claims_suitability"]["top_blockers"] == []
    assert payload["claims_suitability"]["governance_dependency_state"] == "ready"
    assert payload["claims_suitability"]["evidence_gap_state"] == "ready"
    assert "training approval" not in json.dumps(payload["claims_suitability"]).lower()
    assert "export approval" not in json.dumps(payload["claims_suitability"]).lower()


def test_blocked_claims_profile_survives_mila_retrieval_and_pdf_export() -> None:
    headers = _auth_headers()
    document_operations_profile = _document_operations_profile_payload()
    document_operations_profile["claims_profile"] = _claims_profile_payload(
        phi_boundary_review_state="review_required",
        redaction_review_state="missing",
        rate_source_review_state="review_required",
        downstream_consistency_state="blocked",
        downstream_action_approval_state="missing",
        savings_recognition_state="missing",
        governance_claims_control_state="blocked",
    )

    create_response = client.post(
        "/api/v1/assessments/mila/workflow",
        json={
            "org_id": "dev-tenant",
            "org_name": "Default Tenant",
            "workflow_context": _claims_document_operations_workflow_context_payload(),
            "document_operations_profile": document_operations_profile,
            "baseline_operational_score": 84.0,
            "source_system": "mila",
            "source_workflow_type": "document_operations_fixture",
        },
        headers=headers,
    )

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["claims_suitability"]["status"] == "blocked"
    assert payload["claims_suitability"]["score"] == 0.0
    assert payload["claims_suitability"]["governance_dependency_state"] == "blocked"
    assert payload["claims_suitability"]["phi_redaction_state"] == "blocked"
    assert payload["claims_suitability"]["downstream_consistency_state"] == "blocked"

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=headers,
    )
    assert get_response.status_code == 200
    stored_payload = get_response.json()
    assert stored_payload["claims_suitability"] == payload["claims_suitability"]

    export_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}/export/pdf",
        headers=headers,
    )
    assert export_response.status_code == 200
    assert export_response.content.startswith(b"%PDF")
    pdf_text = _extract_pdf_text(export_response.content)
    assert "Claims Suitability" in pdf_text
    assert "claims-hybrid-high-dollar-review-v0" in pdf_text
    assert "Evidence gap: ready" in pdf_text


def test_weak_claims_profile_survives_mila_retrieval_and_pdf_export() -> None:
    headers = _auth_headers()
    document_operations_profile = _document_operations_profile_payload()
    document_operations_profile["claims_profile"] = _claims_profile_payload(
        rate_source_review_state="review_required",
        downstream_consistency_state="review_required",
        savings_recognition_state="review_required",
    )

    create_response = client.post(
        "/api/v1/assessments/mila/workflow",
        json={
            "org_id": "dev-tenant",
            "org_name": "Default Tenant",
            "workflow_context": _claims_document_operations_workflow_context_payload(),
            "document_operations_profile": document_operations_profile,
            "baseline_operational_score": 84.0,
            "source_system": "mila",
            "source_workflow_type": "document_operations_fixture",
        },
        headers=headers,
    )

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["claims_suitability"]["status"] == "weak_candidate"
    assert payload["claims_suitability"]["top_blockers"] == []
    assert payload["claims_suitability"]["rate_source_traceability_state"] == ("review_required")
    assert payload["claims_suitability"]["savings_lifecycle_state"] == "review_required"

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=headers,
    )
    assert get_response.status_code == 200
    stored_payload = get_response.json()
    assert stored_payload["claims_suitability"] == payload["claims_suitability"]

    export_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}/export/pdf",
        headers=headers,
    )
    assert export_response.status_code == 200
    assert export_response.content.startswith(b"%PDF")
    pdf_text = _extract_pdf_text(export_response.content)
    assert "Claims Suitability" in pdf_text
    assert "weak_candidate" in pdf_text
    assert "Evidence gap: ready" in pdf_text


def test_create_assessment_from_upload(tmp_path: Path) -> None:
    _write_dataset(tmp_path)

    files = _upload_files(tmp_path)

    response = client.post("/api/v1/assessments/upload", files=files)

    assert response.status_code == 401

    authorized_response = client.post(
        "/api/v1/assessments/upload",
        files=files,
        headers=_auth_headers(),
    )

    assert authorized_response.status_code == 200
    payload = authorized_response.json()
    assert payload["org_id"] == "org_1"
    assert payload["overall_score"] >= 0


def test_create_assessment_from_upload_with_workflow_context(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    files = _upload_files(tmp_path)

    response = client.post(
        "/api/v1/assessments/upload",
        data={"workflow_context_json": json.dumps(_workflow_context_payload())},
        files=files,
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_mode"] == "workflow"
    assert payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    assert payload["workflow_readiness_score"] is not None


def test_create_assessment_from_upload_rejects_invalid_workflow_context(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    files = _upload_files(tmp_path)

    response = client.post(
        "/api/v1/assessments/upload",
        data={"workflow_context_json": '{"workflow_id":"wf_missing_fields"}'},
        files=files,
        headers=_auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_WORKFLOW_CONTEXT"


def test_create_async_assessment_from_upload(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    headers = _auth_headers()

    files = _upload_files(tmp_path)

    create_response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert create_response.status_code == 202
    payload = create_response.json()
    assert payload["status"] in {"queued", "processing", "completed"}
    assert payload["progress_stage"] == "queued"
    assert payload["progress_percentage"] == 0
    job_id = payload["job_id"]

    final_payload: dict | None = None
    for _ in range(80):
        status_response = client.get(
            f"/api/v1/assessments/async/{job_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] in {"completed", "failed"}:
            final_payload = status_payload
            break
        time.sleep(0.1)

    assert final_payload is not None
    assert final_payload["status"] == "completed"
    assert final_payload["progress_stage"] == "completed"
    assert final_payload["progress_percentage"] == 100
    report_id = final_payload["report_id"]
    assert report_id

    report_response = client.get(
        f"/api/v1/assessments/{report_id}",
        headers=headers,
    )
    assert report_response.status_code == 200
    assert report_response.json()["report_id"] == report_id


def test_create_async_workflow_assessment_from_upload(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    headers = _auth_headers()
    files = _upload_files(tmp_path)

    create_response = client.post(
        "/api/v1/assessments/async/upload",
        data={"workflow_context_json": json.dumps(_workflow_context_payload())},
        files=files,
        headers=headers,
    )
    assert create_response.status_code == 202
    payload = create_response.json()
    assert payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    job_id = payload["job_id"]

    final_payload: dict | None = None
    for _ in range(80):
        status_response = client.get(
            f"/api/v1/assessments/async/{job_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["workflow_context"]["workflow_id"] == "wf_support_triage"
        if status_payload["status"] in {"completed", "failed"}:
            final_payload = status_payload
            break
        time.sleep(0.1)

    assert final_payload is not None
    assert final_payload["status"] == "completed"
    report_id = final_payload["report_id"]
    assert report_id

    report_response = client.get(
        f"/api/v1/assessments/{report_id}",
        headers=headers,
    )
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["assessment_mode"] == "workflow"
    assert report_payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    assert report_payload["workflow_readiness_score"] is not None


def test_async_assessment_submit_rate_limit_enforced(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.async_assessment, "submit_rate_limit_requests", 1)
    monkeypatch.setattr(settings.async_assessment, "submit_rate_limit_window_seconds", 60)
    rate_limiter = get_rate_limiter()
    rate_limiter.clear()
    headers = _signup_and_auth_headers()

    files = _upload_files(tmp_path)
    first_response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert first_response.status_code == 202

    second_response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert second_response.status_code == 429
    assert second_response.json()["detail"]["code"] == "RATE_LIMITED"
    rate_limiter.clear()


def test_async_assessment_queue_limit_enforced(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.async_assessment, "mode", "poll")
    monkeypatch.setattr(settings.async_assessment, "max_outstanding_jobs_per_tenant", 1)
    headers = _signup_and_auth_headers(tenant_id=f"tenant-queue-{uuid4().hex[:8]}")
    files = _upload_files(tmp_path)

    first_response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert first_response.status_code == 202

    second_response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert second_response.status_code == 429
    assert second_response.json()["detail"]["code"] == "ASYNC_QUEUE_LIMIT_REACHED"


def test_async_assessment_upload_file_size_limit(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.async_assessment, "max_upload_bytes_per_file", 20)
    headers = _signup_and_auth_headers()
    files = _upload_files(tmp_path)

    response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["detail"]["code"] == "UPLOAD_FILE_TOO_LARGE"


def test_async_assessment_broker_mode_enqueues_job(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.async_assessment, "mode", "broker")
    enqueued_job_ids: list[str] = []

    class FakeBroker:
        def enqueue(self, job_id: str) -> None:
            enqueued_job_ids.append(job_id)

    monkeypatch.setattr(api_main, "get_async_assessment_broker", lambda: FakeBroker())
    headers = _signup_and_auth_headers(tenant_id=f"tenant-broker-{uuid4().hex[:8]}")
    files = _upload_files(tmp_path)

    response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
    )
    assert response.status_code == 202
    payload = response.json()
    assert enqueued_job_ids == [payload["job_id"]]


def test_scheduled_assessment_crud_flow(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.features, "enable_scheduled_assessments", True)
    headers = _signup_and_auth_headers(tenant_id=f"tenant-schedule-{uuid4().hex[:8]}")
    files = _upload_files(tmp_path)

    create_response = client.post(
        "/api/v1/assessments/schedules/upload",
        data={
            "name": "Daily tenant assessment",
            "cadence": "daily",
            "run_hour_utc": "3",
            "run_minute_utc": "15",
        },
        files=files,
        headers=headers,
    )
    assert create_response.status_code == 201
    schedule_payload = create_response.json()
    assert schedule_payload["status"] == "active"
    assert schedule_payload["cadence"] == "daily"
    schedule_id = schedule_payload["schedule_id"]

    list_response = client.get(
        "/api/v1/assessments/schedules",
        headers=headers,
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert any(item["schedule_id"] == schedule_id for item in listed)

    pause_response = client.post(
        f"/api/v1/assessments/schedules/{schedule_id}/pause",
        headers=headers,
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    resume_response = client.post(
        f"/api/v1/assessments/schedules/{schedule_id}/resume",
        headers=headers,
    )
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "active"


def test_scheduled_workflow_assessment_crud_flow(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.features, "enable_scheduled_assessments", True)
    headers = _signup_and_auth_headers(tenant_id=f"tenant-schedule-{uuid4().hex[:8]}")
    files = _upload_files(tmp_path)

    create_response = client.post(
        "/api/v1/assessments/schedules/upload",
        data={
            "name": "Daily workflow assessment",
            "cadence": "daily",
            "run_hour_utc": "3",
            "run_minute_utc": "15",
            "workflow_context_json": json.dumps(_workflow_context_payload()),
        },
        files=files,
        headers=headers,
    )
    assert create_response.status_code == 201
    schedule_payload = create_response.json()
    assert schedule_payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    schedule_id = schedule_payload["schedule_id"]

    get_response = client.get(
        f"/api/v1/assessments/schedules/{schedule_id}",
        headers=headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["workflow_context"]["workflow_id"] == "wf_support_triage"


def test_list_assessments_and_score_history(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    create_response = client.post(
        "/api/v1/assessments",
        params={"dataset_path": str(tmp_path)},
        headers=_auth_headers(),
    )
    assert create_response.status_code == 200
    created = create_response.json()

    list_response = client.get(
        "/api/v1/assessments",
        params={"limit": 20, "offset": 0},
        headers=_auth_headers(),
    )
    assert list_response.status_code == 200
    reports = list_response.json()
    assert any(report["report_id"] == created["report_id"] for report in reports)

    history_response = client.get(
        "/api/v1/scores/org_1/history",
        params={"limit": 20},
        headers=_auth_headers(),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert history_payload["org_id"] == "org_1"
    assert history_payload["count"] >= 1
    assert history_payload["points"]
    assert "trend_7d" in history_payload
    assert "trend_30d" in history_payload
    assert "trend_90d" in history_payload
    assert "comparison" in history_payload


def test_export_assessment_pdf(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    headers = _auth_headers()
    create_response = client.post(
        "/api/v1/assessments",
        params={"dataset_path": str(tmp_path)},
        headers=headers,
    )
    assert create_response.status_code == 200
    report_id = create_response.json()["report_id"]

    export_response = client.get(
        f"/api/v1/assessments/{report_id}/export/pdf",
        headers=headers,
    )
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/pdf"
    assert "attachment" in export_response.headers["content-disposition"].lower()
    assert export_response.content.startswith(b"%PDF")


def test_sync_assessment_to_opsorchestra_requires_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_dataset(tmp_path)
    headers = _auth_headers()
    create_response = client.post(
        "/api/v1/assessments",
        params={"dataset_path": str(tmp_path)},
        headers=headers,
    )
    assert create_response.status_code == 200
    report_id = create_response.json()["report_id"]

    monkeypatch.setattr(settings.integration, "opsorchestra_outbound_url", None)

    sync_response = client.post(
        f"/api/v1/assessments/{report_id}/sync/opsorchestra",
        headers=headers,
    )
    assert sync_response.status_code == 503
    assert sync_response.json()["detail"]["code"] == "OPSORCHESTRA_SYNC_NOT_CONFIGURED"


def test_sync_assessment_to_opsorchestra_success(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    headers = _auth_headers()
    create_response = client.post(
        "/api/v1/assessments",
        params={"dataset_path": str(tmp_path)},
        headers=headers,
    )
    assert create_response.status_code == 200
    report_id = create_response.json()["report_id"]

    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_outbound_url",
        "https://opsorchestra.example/sync",
    )

    async def _fake_push(
        self,
        *,
        report,
        tenant_id: str,
        actor_id: str,
    ) -> dict[str, object]:
        return {
            "status_code": 202,
            "response": {
                "accepted": True,
                "report_id": report.report_id,
                "tenant_id": tenant_id,
                "actor_id": actor_id,
            },
        }

    monkeypatch.setattr(OpsOrchestraConnector, "push_assessment_report", _fake_push)

    sync_response = client.post(
        f"/api/v1/assessments/{report_id}/sync/opsorchestra",
        headers=headers,
    )
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["status"] == "synced"
    assert payload["assessment_id"] == report_id
    assert payload["opsorchestra"]["status_code"] == 202


def test_pull_entities_from_opsorchestra_requires_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings.integration, "opsorchestra_graph_export_url", None)
    response = client.post(
        "/api/v1/integrations/opsorchestra/pull",
        headers=_auth_headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OPSORCHESTRA_PULL_NOT_CONFIGURED"


def test_pull_entities_from_opsorchestra_success(monkeypatch) -> None:
    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_graph_export_url",
        "https://opsorchestra.example/export",
    )

    async def _fake_pull(
        self,
        *,
        tenant_id: str,
        org_id: str | None = None,
    ) -> dict[str, list]:
        return {
            "organizations": [
                Organization(
                    id="org_pull",
                    name="Pulled Org",
                    headcount_current=20,
                    revenue_current=100000.0,
                    burn_rate_monthly=5000.0,
                    runway_months=12,
                )
            ],
            "teams": [
                Team(
                    id="team_pull",
                    org_id="org_pull",
                    name="Ops",
                    function="operations",
                    headcount_current=7,
                )
            ],
            "systems": [],
            "vendors": [],
            "facilities": [],
            "roles": [],
            "processes": [],
        }

    monkeypatch.setattr(OpsOrchestraConnector, "pull_entities", _fake_pull)

    response = client.post(
        "/api/v1/integrations/opsorchestra/pull",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "imported"
    assert payload["imported_total"] == 2
    assert payload["imported_counts"]["organization"] == 1
    assert payload["imported_counts"]["team"] == 1


def test_pull_entities_from_opsorchestra_success_with_string_entity_types(monkeypatch) -> None:
    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_graph_export_url",
        "https://opsorchestra.example/export",
    )

    async def _fake_pull(
        self,
        *,
        tenant_id: str,
        org_id: str | None = None,
    ) -> dict[str, list]:
        return {
            "organizations": [
                Organization.model_validate(
                    {
                        "id": "org_pull_str",
                        "type": "organization",
                        "name": "Pulled Org (str type)",
                        "headcount_current": 20,
                    }
                )
            ],
            "teams": [
                Team.model_validate(
                    {
                        "id": "team_pull_str",
                        "type": "team",
                        "org_id": "org_pull_str",
                        "name": "Ops",
                        "function": "operations",
                        "headcount_current": 7,
                    }
                )
            ],
            "systems": [],
            "vendors": [],
            "facilities": [],
            "roles": [],
            "processes": [],
        }

    monkeypatch.setattr(OpsOrchestraConnector, "pull_entities", _fake_pull)

    response = client.post(
        "/api/v1/integrations/opsorchestra/pull",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "imported"
    assert payload["imported_total"] == 2
    assert payload["imported_counts"]["organization"] == 1
    assert payload["imported_counts"]["team"] == 1


def test_opsorchestra_token_authentication_when_enabled(tmp_path: Path, monkeypatch) -> None:
    get_opsorchestra_auth_service.cache_clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_path = tmp_path / "opsorchestra-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    monkeypatch.setattr(settings.integration, "opsorchestra_auth_enabled", True)
    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_jwt_public_key_path",
        str(public_key_path),
    )
    monkeypatch.setattr(settings.integration, "opsorchestra_jwt_issuer", "opsorchestra")
    monkeypatch.setattr(settings.integration, "opsorchestra_jwt_audience", "scalescore-api")
    monkeypatch.setattr(settings.integration, "opsorchestra_sub_claim", "sub")
    monkeypatch.setattr(settings.integration, "opsorchestra_tenant_claim", "tenant_id")
    monkeypatch.setattr(settings.integration, "opsorchestra_email_claim", "email")
    monkeypatch.setattr(settings.integration, "opsorchestra_roles_claim", "roles")

    token = _issue_opsorchestra_token(
        private_key=private_key,
        tenant_id="ops-tenant",
        roles=["admin"],
    )

    response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_opsorchestra_token_auth_returns_503_when_unconfigured(monkeypatch) -> None:
    get_opsorchestra_auth_service.cache_clear()
    monkeypatch.setattr(settings.integration, "opsorchestra_auth_enabled", True)
    monkeypatch.setattr(settings.integration, "opsorchestra_jwt_public_key_path", None)
    monkeypatch.setattr(settings.integration, "opsorchestra_jwks_url", None)

    response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OPSORCHESTRA_AUTH_NOT_CONFIGURED"


def test_external_oidc_token_authentication_when_enabled(tmp_path: Path, monkeypatch) -> None:
    get_external_oidc_auth_service.cache_clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_path = tmp_path / "external-oidc-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    monkeypatch.setattr(settings.integration, "external_oidc_auth_enabled", True)
    monkeypatch.setattr(
        settings.integration,
        "external_oidc_jwt_public_key_path",
        str(public_key_path),
    )
    monkeypatch.setattr(settings.integration, "external_oidc_jwks_url", None)
    monkeypatch.setattr(
        settings.integration, "external_oidc_jwt_issuer", "https://idp.example.com/"
    )
    monkeypatch.setattr(settings.integration, "external_oidc_jwt_audience", "scalescore-api")
    monkeypatch.setattr(settings.integration, "external_oidc_sub_claim", "sub")
    monkeypatch.setattr(settings.integration, "external_oidc_tenant_claim", "tid")
    monkeypatch.setattr(settings.integration, "external_oidc_email_claim", "email")
    monkeypatch.setattr(settings.integration, "external_oidc_roles_claim", "groups")

    token = _issue_external_oidc_token(
        private_key=private_key,
        tenant_id="tenant-oidc",
        roles=["admin"],
    )

    response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_external_oidc_token_auth_returns_503_when_unconfigured(monkeypatch) -> None:
    get_external_oidc_auth_service.cache_clear()
    monkeypatch.setattr(settings.integration, "external_oidc_auth_enabled", True)
    monkeypatch.setattr(settings.integration, "external_oidc_jwt_public_key_path", None)
    monkeypatch.setattr(settings.integration, "external_oidc_jwks_url", None)
    monkeypatch.setattr(
        settings.integration, "external_oidc_jwt_issuer", "https://idp.example.com/"
    )

    response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EXTERNAL_OIDC_AUTH_NOT_CONFIGURED"


def test_opsorchestra_token_auth_returns_503_when_key_service_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    get_opsorchestra_auth_service.cache_clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_path = tmp_path / "opsorchestra-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    monkeypatch.setattr(settings.integration, "opsorchestra_auth_enabled", True)
    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_jwt_public_key_path",
        str(public_key_path),
    )
    monkeypatch.setattr(settings.integration, "opsorchestra_jwks_url", None)

    def _raise_service_unavailable(self, token: str) -> None:
        raise ScaleScoreError(
            message="Failed to fetch OpsOrchestra JWKS",
            code=ErrorCode.EXTERNAL_SERVICE_ERROR,
        )

    monkeypatch.setattr(
        OpsOrchestraAuthService,
        "verify_parent_token",
        _raise_service_unavailable,
    )

    response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == ErrorCode.EXTERNAL_SERVICE_ERROR.value


def test_refresh_flow_returns_usable_access_token() -> None:
    refresh_token = _login()["refresh_token"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 200
    refreshed_access_token = refresh_response.json()["access_token"]

    list_response = client.get(
        "/api/v1/assessments",
        headers={"Authorization": f"Bearer {refreshed_access_token}"},
    )
    assert list_response.status_code == 200


def test_signup_then_login() -> None:
    email = f"user-{uuid4().hex[:8]}@example.com"
    signup_response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "strong-password",
            "tenant_id": "tenant-signup",
            "org_id": "org-signup",
            "roles": ["analyst"],
        },
    )
    assert signup_response.status_code == 201
    payload = signup_response.json()
    assert payload["email"] == email
    assert payload["tenant_id"] == "tenant-signup"

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "strong-password"},
    )
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()


def test_signup_rejects_elevated_roles() -> None:
    rate_limiter = get_rate_limiter()
    rate_limiter.clear()

    for role in ("admin", "super_admin"):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"user-{uuid4().hex[:8]}@example.com",
                "password": "strong-password",
                "tenant_id": f"tenant-{uuid4().hex[:8]}",
                "org_id": "org-signup",
                "roles": [role],
            },
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ELEVATED_SIGNUP_ROLE_NOT_ALLOWED"

    rate_limiter.clear()


def test_production_signup_disabled_by_default(monkeypatch) -> None:
    rate_limiter = get_rate_limiter()
    rate_limiter.clear()
    monkeypatch.setattr(settings, "environment", "production")

    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"user-{uuid4().hex[:8]}@example.com",
            "password": "strong-password",
            "tenant_id": f"tenant-{uuid4().hex[:8]}",
            "org_id": "org-signup",
            "roles": ["analyst"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PUBLIC_SIGNUP_DISABLED"
    rate_limiter.clear()


def test_login_rate_limit_enforced(monkeypatch) -> None:
    rate_limiter = get_rate_limiter()
    rate_limiter.clear()
    monkeypatch.setattr(settings.auth, "login_rate_limit_requests", 1)
    monkeypatch.setattr(settings.auth, "login_rate_limit_window_seconds", 60)

    first = client.post(
        "/api/v1/auth/login",
        json={"email": "dev@example.com", "password": "dev"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/auth/login",
        json={"email": "dev@example.com", "password": "dev"},
    )
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "RATE_LIMITED"
    rate_limiter.clear()


def test_all_required_routes_use_async_shared_limiter(tmp_path: Path, monkeypatch) -> None:
    _write_dataset(tmp_path)
    tokens = _login()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    monkeypatch.setattr(settings.features, "enable_async_assessments", True)
    monkeypatch.setattr(settings.features, "enable_scheduled_assessments", True)
    limiter = DenyAllRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        responses = [
            client.post(
                "/api/v1/auth/login",
                json={"email": "dev@example.com", "password": "dev"},
            ),
            client.post(
                "/api/v1/auth/signup",
                json={
                    "email": f"limited-{uuid4().hex[:8]}@example.com",
                    "password": "strong-password",
                    "tenant_id": "limited-tenant",
                    "roles": ["analyst"],
                },
            ),
            client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            ),
            client.post(
                "/api/v1/auth/api-keys",
                headers=headers,
                json={"name": "limited key", "expires_in_days": 30},
            ),
            client.post(
                "/api/v1/assessments/async/upload",
                headers=headers,
                files=_upload_files(tmp_path),
            ),
            client.post(
                "/api/v1/assessments/schedules/upload",
                headers=headers,
                data={
                    "name": "limited schedule",
                    "cadence": "daily",
                    "run_hour_utc": 2,
                    "run_minute_utc": 30,
                },
                files=_upload_files(tmp_path),
            ),
        ]
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)

    assert limiter.calls == 6
    for response in responses:
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "17"
        assert response.json()["detail"] == {
            "code": "RATE_LIMITED",
            "message": "Rate limit exceeded, retry later",
            "retry_after_seconds": 17,
        }


def test_auth_me_requires_authentication() -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_api_key_authentication_flow() -> None:
    token = _login()["access_token"]
    create_key_response = client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "e2e key"},
    )
    assert create_key_response.status_code == 201
    key_payload = create_key_response.json()
    api_key = key_payload["api_key"]
    key_id = key_payload["key_id"]

    api_key_list_response = client.get(
        "/api/v1/assessments",
        headers={"X-API-Key": api_key},
    )
    assert api_key_list_response.status_code == 200

    revoke_response = client.delete(
        f"/api/v1/auth/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_response.status_code == 200

    revoked_key_response = client.get(
        "/api/v1/assessments",
        headers={"X-API-Key": api_key},
    )
    assert revoked_key_response.status_code == 401


def test_api_key_roles_must_be_subset_of_current_principal() -> None:
    headers = _signup_and_auth_headers()

    response = client.post(
        "/api/v1/auth/api-keys",
        headers=headers,
        json={"name": "escalating e2e key", "roles": ["admin"]},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "API_KEY_ROLE_ESCALATION_NOT_ALLOWED"


def test_api_key_creation_rejects_non_expiring_keys() -> None:
    headers = _signup_and_auth_headers()

    response = client.post(
        "/api/v1/auth/api-keys",
        headers=headers,
        json={"name": "non expiring e2e key", "expires_in_days": None},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "NON_EXPIRING_API_KEYS_NOT_ALLOWED"


def test_api_key_principal_cannot_create_child_api_key() -> None:
    headers = _signup_and_auth_headers()
    create_response = client.post(
        "/api/v1/auth/api-keys",
        headers=headers,
        json={"name": "parent e2e key", "expires_in_days": 30},
    )
    assert create_response.status_code == 201
    parent_api_key = create_response.json()["api_key"]

    child_response = client.post(
        "/api/v1/auth/api-keys",
        headers={"X-API-Key": parent_api_key},
        json={"name": "child e2e key", "expires_in_days": 30, "roles": ["analyst"]},
    )

    assert child_response.status_code == 403
    assert child_response.json()["detail"]["code"] == "API_KEY_DELEGATION_NOT_ALLOWED"


def test_opsorchestra_webhook_secret_enforced_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        settings.integration,
        "opsorchestra_webhook_secret",
        SecretStr("test-webhook-secret"),
    )

    payload = {
        "event_type": "entity.deleted",
        "tenant_id": "tenant-webhook",
        "entity_type": "team",
        "entity_id": "team-webhook",
    }

    missing_secret_response = client.post("/api/v1/webhooks/opsorchestra", json=payload)
    assert missing_secret_response.status_code == 401

    wrong_secret_response = client.post(
        "/api/v1/webhooks/opsorchestra",
        json=payload,
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert wrong_secret_response.status_code == 401

    valid_secret_response = client.post(
        "/api/v1/webhooks/opsorchestra",
        json=payload,
        headers={"X-Webhook-Secret": "test-webhook-secret"},
    )
    assert valid_secret_response.status_code == 200
    assert valid_secret_response.json()["status"] == "processed"


def test_opsorchestra_webhook_requires_configured_secret_in_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings.integration, "opsorchestra_webhook_secret", None)

    response = client.post(
        "/api/v1/webhooks/opsorchestra",
        json={
            "event_type": "entity.deleted",
            "tenant_id": "tenant-webhook",
            "entity_type": "team",
            "entity_id": "team-webhook",
        },
    )
    assert response.status_code == 503


def test_organization_crud_flow() -> None:
    headers = _auth_headers()
    organization_payload = {
        "id": f"org-{uuid4().hex[:8]}",
        "name": "Roadrunner Inc",
        "type": "organization",
        "headcount_current": 120,
        "revenue_current": 2_500_000,
        "burn_rate_monthly": 120_000,
        "runway_months": 18,
    }

    create_response = client.post(
        "/api/v1/organizations",
        json=organization_payload,
        headers=headers,
    )
    assert create_response.status_code == 200
    org_id = create_response.json()["id"]

    list_response = client.get("/api/v1/organizations", headers=headers)
    assert list_response.status_code == 200
    assert any(item["id"] == org_id for item in list_response.json())

    update_payload = {**organization_payload, "name": "Roadrunner Holdings"}
    update_response = client.put(
        f"/api/v1/organizations/{org_id}",
        json=update_payload,
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Roadrunner Holdings"

    delete_response = client.delete(f"/api/v1/organizations/{org_id}", headers=headers)
    assert delete_response.status_code == 200

    get_deleted_response = client.get(f"/api/v1/organizations/{org_id}", headers=headers)
    assert get_deleted_response.status_code == 404


def test_csv_import_persists_entities(tmp_path: Path) -> None:
    headers = _auth_headers()
    teams_file = tmp_path / "teams.csv"
    teams_file.write_text(
        "id,org_id,name,function,headcount_current,parent_team_id,manager_id\n"
        "team_import_1,org_1,Growth,growth,12,,mgr_9\n",
        encoding="utf-8",
    )

    with teams_file.open("rb") as fh:
        import_response = client.post(
            "/api/v1/import/csv",
            params={"entity_type": "teams"},
            files={"file": ("teams.csv", fh, "text/csv")},
            headers=headers,
        )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload["status"] == "imported"
    assert payload["imported_count"] == 1

    list_response = client.get(
        "/api/v1/entities/teams",
        params={"org_id": "org_1"},
        headers=headers,
    )
    assert list_response.status_code == 200
    assert any(item["id"] == "team_import_1" for item in list_response.json())


def test_opsorchestra_webhook_upsert_and_delete_entity() -> None:
    upsert_response = client.post(
        "/api/v1/webhooks/opsorchestra",
        json={
            "event_type": "entity.updated",
            "tenant_id": "dev-tenant",
            "event_id": f"evt-{uuid4().hex[:8]}",
            "entity_type": "team",
            "entity_id": "team_hook_1",
            "entity": {
                "id": "team_hook_1",
                "org_id": "org_1",
                "name": "Webhook Team",
                "function": "operations",
                "headcount_current": 9,
            },
        },
    )
    assert upsert_response.status_code == 200
    assert upsert_response.json()["action"] == "upserted"

    list_response = client.get(
        "/api/v1/entities/teams",
        params={"org_id": "org_1"},
        headers=_auth_headers(),
    )
    assert list_response.status_code == 200
    assert any(item["id"] == "team_hook_1" for item in list_response.json())

    delete_response = client.post(
        "/api/v1/webhooks/opsorchestra",
        json={
            "event_type": "entity.deleted",
            "tenant_id": "dev-tenant",
            "event_id": f"evt-{uuid4().hex[:8]}",
            "entity_type": "team",
            "entity_id": "team_hook_1",
        },
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["action"] in {"deleted", "not_found"}

    get_response = client.get(
        "/api/v1/entities/teams/team_hook_1",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 404
