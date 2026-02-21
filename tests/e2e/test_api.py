from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from scalescore.api.main import app

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

    get_response = client.get(
        f"/api/v1/assessments/{payload['report_id']}",
        headers=_auth_headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["report_id"] == payload["report_id"]


def test_create_assessment_from_upload(tmp_path: Path) -> None:
    _write_dataset(tmp_path)

    files = {
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
