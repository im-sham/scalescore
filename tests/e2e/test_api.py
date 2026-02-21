from pathlib import Path

from fastapi.testclient import TestClient

from scalescore.api.main import app

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "dev@example.com", "password": "dev"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
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


def test_refresh_flow_returns_usable_access_token() -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "dev@example.com", "password": "dev"},
    )
    assert login_response.status_code == 200
    refresh_token = login_response.json()["refresh_token"]

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
