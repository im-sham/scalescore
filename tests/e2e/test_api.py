import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
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
from scalescore.core.rate_limit import get_rate_limiter
from scalescore.models.core import Organization, Team

client = TestClient(app)


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


def test_create_mila_workflow_assessment_direct() -> None:
    response = client.post(
        "/api/v1/assessments/mila/workflow",
        json={
            "org_id": "tenant_default",
            "org_name": "Default Tenant",
            "workflow_context": _workflow_context_payload(),
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
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_mode"] == "workflow"
    assert payload["org_id"] == "tenant_default"
    assert payload["org_name"] == "Default Tenant"
    assert payload["workflow_context"]["workflow_id"] == "wf_support_triage"
    assert payload["workflow_readiness_score"] is not None
    assert payload["overall_score"] == payload["workflow_readiness_score"]
    assert "Runbook readiness is 90% (at_risk)." in payload["key_findings"]

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["report_id"] == payload["report_id"]


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
        data={"workflow_context_json": "{\"workflow_id\":\"wf_missing_fields\"}"},
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
