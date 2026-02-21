from __future__ import annotations

import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError
from scalescore.models.scaling import ScaleScoreReport


class AssessmentRepository(Protocol):
    def save_report(self, report: ScaleScoreReport, tenant_id: str) -> None: ...

    def get_report(self, report_id: str, tenant_id: str) -> ScaleScoreReport | None: ...

    def list_reports(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[ScaleScoreReport]: ...

    def list_history(
        self,
        tenant_id: str,
        *,
        org_id: str,
        limit: int,
    ) -> list[ScaleScoreReport]: ...


class SQLiteAssessmentRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assessment_reports (
                            report_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            org_id TEXT NOT NULL,
                            report_version TEXT NOT NULL,
                            generated_at TEXT NOT NULL,
                            report_data TEXT NOT NULL,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_assessment_reports_tenant_created
                        ON assessment_reports (tenant_id, created_at DESC)
                        """
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize assessment storage", cause=err) from err

    def save_report(self, report: ScaleScoreReport, tenant_id: str) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
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
                            report.report_id,
                            tenant_id,
                            report.org_id,
                            report.report_version,
                            report.generated_at.isoformat(),
                            report.model_dump_json(),
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to persist assessment report", cause=err) from err

    def get_report(self, report_id: str, tenant_id: str) -> ScaleScoreReport | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT report_data
                    FROM assessment_reports
                    WHERE report_id = ? AND tenant_id = ?
                    """,
                    (report_id, tenant_id),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load assessment report", cause=err) from err

        if row is None:
            return None

        return ScaleScoreReport.model_validate_json(row["report_data"])

    def list_reports(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[ScaleScoreReport]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT report_data
                    FROM assessment_reports
                    WHERE tenant_id = ?
                    ORDER BY generated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (tenant_id, limit, offset),
                ).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to list assessment reports", cause=err) from err

        return [ScaleScoreReport.model_validate_json(row["report_data"]) for row in rows]

    def list_history(
        self,
        tenant_id: str,
        *,
        org_id: str,
        limit: int,
    ) -> list[ScaleScoreReport]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT report_data
                    FROM assessment_reports
                    WHERE tenant_id = ? AND org_id = ?
                    ORDER BY generated_at DESC
                    LIMIT ?
                    """,
                    (tenant_id, org_id, limit),
                ).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load score history", cause=err) from err

        return [ScaleScoreReport.model_validate_json(row["report_data"]) for row in rows]


@lru_cache
def get_assessment_repository() -> SQLiteAssessmentRepository:
    return SQLiteAssessmentRepository(settings.storage.assessments_db_path)
