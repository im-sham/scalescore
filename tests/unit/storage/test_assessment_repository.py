import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scalescore.connectors.opsorchestra_connector import OpsOrchestraConnector
from scalescore.contracts.assessment_ref import AssessmentRefEnvelope
from scalescore.core.reporting import render_report_pdf
from scalescore.models.scaling import ScaleScoreReport
from scalescore.storage.assessment_repository import SQLiteAssessmentRepository


def _report(
    report_id: str,
    org_id: str = "org_1",
    *,
    generated_at: datetime | None = None,
    score: float = 80.0,
) -> ScaleScoreReport:
    return ScaleScoreReport(
        report_id=report_id,
        org_id=org_id,
        org_name="Acme",
        generated_at=generated_at or datetime.now(UTC),
        overall_score=score,
    )


def _persist_raw_report(db_path: Path, report_data: dict[str, object]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO assessment_reports (
                report_id,
                tenant_id,
                org_id,
                report_version,
                generated_at,
                report_data
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report_data["report_id"],
                "tenant_a",
                report_data["org_id"],
                report_data["report_version"],
                report_data["generated_at"],
                json.dumps(report_data),
            ),
        )


def _canonical_assessment_ref_payload() -> dict[str, object]:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "vendor"
        / "proofhouse-contracts"
        / "contracts"
        / "assessment-ref"
        / "v0.1"
        / "fixtures"
        / "synthetic-assessment.json"
    )
    return json.loads(fixture_path.read_text())


def _legacy_unattributed_operational_learning_report(
    report_id: str,
) -> dict[str, object]:
    report_data = _report(report_id).model_dump(mode="json")
    report_data["operational_learning_suitability"] = {
        "status": "training_candidate",
        "dimension_scores": [],
        "eval_suitability": {
            "score": 90.0,
            "status": "eval_suitable",
            "threshold": 70.0,
            "threshold_met": True,
            "hard_blocked": False,
        },
        "internal_training_candidacy": {
            "score": 90.0,
            "status": "training_candidate",
            "threshold": 80.0,
            "threshold_met": True,
            "hard_blocked": False,
        },
        "top_blockers": [],
        "top_reasons": ["Legacy dependency posture was complete."],
        "recommended_next_actions": [],
        "governance_dependency_state": {
            "rights_completeness": "complete",
            "provenance_completeness": "complete",
            "redaction_readiness": "complete",
            "residual_risk_band": "low",
            "status": "ready",
            "summary": "Legacy dependency posture was complete.",
        },
    }
    report_data["executive_summary"] = (
        "Operational Learning suitability is training candidate with score 90."
    )
    legacy_action = "Advance this workflow to internal training candidacy."
    report_data["immediate_actions"] = [legacy_action]
    suitability = report_data["operational_learning_suitability"]
    assert isinstance(suitability, dict)
    suitability["recommended_next_actions"] = [legacy_action]
    return report_data


def test_repository_suppresses_legacy_unattributed_operational_learning_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "reports.sqlite3"
    drawn_strings: list[str] = []

    class FakeCanvas:
        def __init__(self, buffer, pagesize) -> None:
            self._buffer = buffer
            self._pagesize = pagesize

        def setFont(self, font: str, size: int) -> None:
            return None

        def drawString(self, x: int, y: int, text: str) -> None:
            drawn_strings.append(text)

        def drawRightString(self, x: int, y: int, text: str) -> None:
            drawn_strings.append(text)

        def showPage(self) -> None:
            return None

        def save(self) -> None:
            self._buffer.write(b"%PDF fake")

    monkeypatch.setattr("scalescore.core.reporting.canvas.Canvas", FakeCanvas)
    repository = SQLiteAssessmentRepository(db_path)
    report_data = _legacy_unattributed_operational_learning_report("report_legacy_ol")
    assessment_ref = _canonical_assessment_ref_payload()
    assessment_ref["ref"]["assessment_type"] = "operational_learning_suitability"
    assessment_ref["ref"]["summary"] = "Legacy Operational Learning eligibility summary."
    report_data["assessment_ref"] = assessment_ref

    with pytest.raises(ValidationError, match="evidence_basis"):
        ScaleScoreReport.model_validate(report_data)

    _persist_raw_report(db_path, report_data)
    with sqlite3.connect(db_path) as connection:
        stored_before_load = connection.execute(
            "SELECT report_data FROM assessment_reports WHERE report_id = ?",
            ("report_legacy_ol",),
        ).fetchone()[0]

    loaded = repository.get_report("report_legacy_ol", tenant_id="tenant_a")
    reports = repository.list_reports("tenant_a", limit=10, offset=0)
    history = repository.list_history("tenant_a", org_id="org_1", limit=10)
    assert loaded is not None
    assert loaded.operational_learning_suitability is None
    assert loaded.assessment_ref is None
    assert "training candidate" not in loaded.executive_summary
    assert loaded.immediate_actions == []
    assert [report.report_id for report in reports] == ["report_legacy_ol"]
    assert reports[0].operational_learning_suitability is None
    assert [report.report_id for report in history] == ["report_legacy_ol"]
    assert history[0].operational_learning_suitability is None
    assert OpsOrchestraConnector._operational_learning_suitability_summary(loaded) is None
    assert render_report_pdf(loaded) == b"%PDF fake"
    pdf_text = " ".join(drawn_strings)
    assert "training candidate" not in pdf_text
    assert "score 90" not in pdf_text
    with sqlite3.connect(db_path) as connection:
        stored_after_load = connection.execute(
            "SELECT report_data FROM assessment_reports WHERE report_id = ?",
            ("report_legacy_ol",),
        ).fetchone()[0]
    assert stored_after_load == stored_before_load


def test_legacy_ol_suppression_preserves_workflow_readiness_assessment_ref(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reports.sqlite3"
    repository = SQLiteAssessmentRepository(db_path)
    report_data = _legacy_unattributed_operational_learning_report("report_legacy_ol_workflow_ref")
    report_data["assessment_ref"] = _canonical_assessment_ref_payload()
    _persist_raw_report(db_path, report_data)

    loaded = repository.get_report(
        "report_legacy_ol_workflow_ref",
        tenant_id="tenant_a",
    )

    assert loaded is not None
    assert loaded.operational_learning_suitability is None
    assert loaded.assessment_ref is not None
    assert loaded.assessment_ref.ref.assessment_type == "workflow_readiness"


def test_save_and_get_report(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    report = _report("report_1")

    repository.save_report(report, tenant_id="tenant_a")
    loaded = repository.get_report("report_1", tenant_id="tenant_a")

    assert loaded is not None
    assert loaded.report_id == report.report_id
    assert loaded.org_id == report.org_id
    assert loaded.overall_score == report.overall_score


def test_get_report_is_tenant_scoped(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    report = _report("report_1")

    repository.save_report(report, tenant_id="tenant_a")
    loaded = repository.get_report("report_1", tenant_id="tenant_b")

    assert loaded is None


def test_list_reports_supports_pagination(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    repository.save_report(
        _report("report_1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)), "tenant_a"
    )
    repository.save_report(
        _report("report_2", generated_at=datetime(2026, 1, 2, tzinfo=UTC)), "tenant_a"
    )
    repository.save_report(
        _report("report_3", generated_at=datetime(2026, 1, 3, tzinfo=UTC)), "tenant_a"
    )

    page = repository.list_reports("tenant_a", limit=2, offset=0)
    second_page = repository.list_reports("tenant_a", limit=2, offset=2)

    assert [report.report_id for report in page] == ["report_3", "report_2"]
    assert [report.report_id for report in second_page] == ["report_1"]


def test_list_history_scopes_by_org_and_tenant(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    repository.save_report(
        _report("report_org1_old", org_id="org_1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        tenant_id="tenant_a",
    )
    repository.save_report(
        _report("report_org1_new", org_id="org_1", generated_at=datetime(2026, 1, 2, tzinfo=UTC)),
        tenant_id="tenant_a",
    )
    repository.save_report(
        _report("report_org2", org_id="org_2", generated_at=datetime(2026, 1, 3, tzinfo=UTC)),
        tenant_id="tenant_a",
    )
    repository.save_report(
        _report(
            "report_other_tenant", org_id="org_1", generated_at=datetime(2026, 1, 4, tzinfo=UTC)
        ),
        tenant_id="tenant_b",
    )

    history = repository.list_history("tenant_a", org_id="org_1", limit=10)

    assert [report.report_id for report in history] == ["report_org1_new", "report_org1_old"]


def test_get_report_omits_legacy_assessment_ref_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "reports.sqlite3"
    repository = SQLiteAssessmentRepository(db_path)
    report_data = _report("report_legacy").model_dump(mode="json")
    report_data["assessment_ref"] = {
        "contract_version": "proofhouse-shared-contracts/v0.1",
        "contract_name": "AssessmentRef",
        "producer_capability": "readiness",
        "producer_system": "proofhouse-readiness",
        "canonical_owner": "readiness",
        "issued_at": "2026-07-17T16:00:00Z",
        "cache_policy": "summary_snapshot",
        "ref": {
            "ref_id": "assessment:org_1:report_legacy",
            "ref_type": "assessment",
            "source_capability": "readiness",
            "organization_id": "org_1",
            "environment_id": "test",
            "external_uri": None,
            "snapshot_id": None,
            "version": None,
            "created_at": "2026-07-17T16:00:00Z",
            "summary": "Legacy assessment summary.",
            "assessment_id": "report_legacy",
            "workflow_id": None,
            "workflow_ref": None,
            "assessment_type": "workflow_readiness",
            "score": 80.0,
            "grade": "B",
            "status": "ready",
            "top_blockers": [],
            "top_reasons": [],
            "report_uri": None,
        },
    }
    _persist_raw_report(db_path, report_data)

    loaded = repository.get_report("report_legacy", tenant_id="tenant_a")

    assert loaded is not None
    assert loaded.report_id == "report_legacy"
    assert loaded.overall_score == 80.0
    assert loaded.assessment_ref is None


def test_get_report_round_trips_canonical_assessment_ref(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "vendor"
        / "proofhouse-contracts"
        / "contracts"
        / "assessment-ref"
        / "v0.1"
        / "fixtures"
        / "synthetic-assessment.json"
    )
    assessment_ref = AssessmentRefEnvelope.model_validate_json(fixture_path.read_text())
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    report = _report("report_canonical")
    report.assessment_ref = assessment_ref

    repository.save_report(report, tenant_id="tenant_a")
    loaded = repository.get_report("report_canonical", tenant_id="tenant_a")

    assert loaded is not None
    assert loaded.assessment_ref == assessment_ref


def test_get_report_rejects_malformed_canonical_assessment_ref(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "vendor"
        / "proofhouse-contracts"
        / "contracts"
        / "assessment-ref"
        / "v0.1"
        / "fixtures"
        / "synthetic-assessment.json"
    )
    assessment_ref = json.loads(fixture_path.read_text())
    del assessment_ref["ref"]["workflow_ref"]
    db_path = tmp_path / "reports.sqlite3"
    repository = SQLiteAssessmentRepository(db_path)
    report_data = _report("report_malformed").model_dump(mode="json")
    report_data["assessment_ref"] = assessment_ref
    _persist_raw_report(db_path, report_data)

    with pytest.raises(ValidationError, match="workflow_ref"):
        repository.get_report("report_malformed", tenant_id="tenant_a")
