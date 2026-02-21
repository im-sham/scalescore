from pathlib import Path

import pytest

from scalescore.config import settings
from scalescore.core.assessment import run_assessment, run_assessment_from_csv
from scalescore.models.core import Facility, Organization, System
from scalescore.models.scaling import FunctionalArea


def test_run_assessment_builds_constraints_and_scores() -> None:
    organization = Organization(id="org_1", name="Acme")
    system = System(
        id="sys_1",
        org_id="org_1",
        name="Billing",
        system_type="erp",
        capacity_current=90,
        capacity_max=100,
        capacity_unit="users",
    )
    facility = Facility(
        id="fac_1",
        org_id="org_1",
        name="HQ",
        facility_type="office",
        location="SF",
        capacity_seats=100,
        capacity_used=90,
    )

    report = run_assessment(
        organizations=[organization],
        systems=[system],
        facilities=[facility],
        growth_signals=[],
    )

    assert report.total_constraints == 2
    assert report.area_scores
    assert report.overall_score < 100


def test_run_assessment_rejects_multiple_orgs() -> None:
    from scalescore.core.exceptions import MultipleOrganizationsError

    org_a = Organization(id="org_a", name="Acme")
    org_b = Organization(id="org_b", name="Beta")

    with pytest.raises(MultipleOrganizationsError, match="single organization"):
        run_assessment(
            organizations=[org_a, org_b],
            systems=[],
            facilities=[],
            growth_signals=[],
        )


def test_run_assessment_uses_settings_based_scoring(monkeypatch) -> None:
    monkeypatch.setattr(settings.scoring, "base_score", 82.0)

    report = run_assessment(
        organizations=[Organization(id="org_1", name="Acme")],
        systems=[],
        facilities=[],
        growth_signals=[],
    )

    assert report.overall_score == 82.0
    assert report.area_scores
    assert all(score.score == 82.0 for score in report.area_scores)


def test_run_assessment_from_csv(tmp_path: Path) -> None:
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

    report = run_assessment_from_csv(tmp_path)

    assert report.org_id == "org_1"
    assert report.area_scores
    assert report.area_scores[0].functional_area in {
        FunctionalArea.ENGINEERING,
        FunctionalArea.OPERATIONS,
        FunctionalArea.FACILITIES,
    }
