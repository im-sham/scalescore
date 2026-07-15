import sqlite3
from datetime import UTC, datetime
from pathlib import Path

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


def _index_columns(db_path: Path, index_name: str) -> list[tuple[str, bool]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            (row["name"], bool(row["desc"]))
            for row in connection.execute(f"PRAGMA index_xinfo({index_name})")
            if row["key"]
        ]


def test_save_and_get_report(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    report = _report("report_1")

    repository.save_report(report, tenant_id="tenant_a")
    loaded = repository.get_report("report_1", tenant_id="tenant_a")

    assert loaded is not None
    assert loaded.report_id == report.report_id
    assert loaded.org_id == report.org_id
    assert loaded.overall_score == report.overall_score


def test_report_list_query_has_generated_at_index(tmp_path: Path) -> None:
    db_path = tmp_path / "reports.sqlite3"
    SQLiteAssessmentRepository(db_path)

    assert _index_columns(
        db_path, "idx_assessment_reports_tenant_generated_at"
    ) == [
        ("tenant_id", False),
        ("generated_at", True),
    ]


def test_report_history_query_has_org_generated_at_index(tmp_path: Path) -> None:
    db_path = tmp_path / "reports.sqlite3"
    SQLiteAssessmentRepository(db_path)

    assert _index_columns(
        db_path, "idx_assessment_reports_tenant_org_generated_at"
    ) == [
        ("tenant_id", False),
        ("org_id", False),
        ("generated_at", True),
    ]


def test_get_report_is_tenant_scoped(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    report = _report("report_1")

    repository.save_report(report, tenant_id="tenant_a")
    loaded = repository.get_report("report_1", tenant_id="tenant_b")

    assert loaded is None


def test_list_reports_supports_pagination(tmp_path) -> None:
    repository = SQLiteAssessmentRepository(tmp_path / "reports.sqlite3")
    repository.save_report(_report("report_1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)), "tenant_a")
    repository.save_report(_report("report_2", generated_at=datetime(2026, 1, 2, tzinfo=UTC)), "tenant_a")
    repository.save_report(_report("report_3", generated_at=datetime(2026, 1, 3, tzinfo=UTC)), "tenant_a")

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
        _report("report_other_tenant", org_id="org_1", generated_at=datetime(2026, 1, 4, tzinfo=UTC)),
        tenant_id="tenant_b",
    )

    history = repository.list_history("tenant_a", org_id="org_1", limit=10)

    assert [report.report_id for report in history] == ["report_org1_new", "report_org1_old"]
