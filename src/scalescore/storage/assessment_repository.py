from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError
from scalescore.core.reporting import generate_executive_summary
from scalescore.models.scaling import ScaleScoreReport

_CANONICAL_ASSESSMENT_REF_MARKERS = frozenset(
    {
        "contract_version",
        "contract_name",
        "producer_capability",
        "producer_system",
        "canonical_owner",
    }
)
_LEGACY_ASSESSMENT_REF_FIELDS = frozenset({"workflow_id", "report_uri"})
_OPERATIONAL_LEARNING_POSTURE_FIELDS = frozenset(
    {
        "rights_completeness",
        "provenance_completeness",
        "redaction_readiness",
        "residual_risk_band",
    }
)


def _load_report(report_data: str) -> ScaleScoreReport:
    payload = json.loads(report_data)
    suppressed_legacy_operational_learning = False
    if isinstance(payload, dict):
        assessment_ref = payload.get("assessment_ref")
        if _has_legacy_unattributed_operational_learning_posture(payload):
            suitability = payload.get("operational_learning_suitability")
            if isinstance(suitability, dict):
                recommended_actions = suitability.get("recommended_next_actions")
                if (
                    isinstance(recommended_actions, list)
                    and payload.get("immediate_actions") == recommended_actions[:3]
                ):
                    payload["immediate_actions"] = []
            payload.pop("operational_learning_suitability", None)
            if _is_operational_learning_assessment_ref(assessment_ref):
                payload.pop("assessment_ref", None)
            suppressed_legacy_operational_learning = True
        if _should_suppress_assessment_ref(payload.get("assessment_ref")):
            payload.pop("assessment_ref", None)

    report = ScaleScoreReport.model_validate(payload)
    if suppressed_legacy_operational_learning:
        report.executive_summary = generate_executive_summary(report)
    return report


def _has_legacy_unattributed_operational_learning_posture(
    payload: dict[str, object],
) -> bool:
    suitability = payload.get("operational_learning_suitability")
    if not isinstance(suitability, dict):
        return False
    dependency_state = suitability.get("governance_dependency_state")
    if not isinstance(dependency_state, dict):
        return False
    has_posture = any(
        dependency_state.get(field) is not None for field in _OPERATIONAL_LEARNING_POSTURE_FIELDS
    )
    return (
        has_posture
        and "evidence_basis" not in dependency_state
        and "evidence_ref_id" not in dependency_state
    )


def _is_operational_learning_assessment_ref(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    ref = value.get("ref")
    return (
        isinstance(ref, dict) and ref.get("assessment_type") == "operational_learning_suitability"
    )


def _should_suppress_assessment_ref(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, dict):
        return True

    ref = value.get("ref")
    if isinstance(ref, dict) and _LEGACY_ASSESSMENT_REF_FIELDS.intersection(ref):
        return True

    return not _CANONICAL_ASSESSMENT_REF_MARKERS.intersection(value)


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

        return _load_report(row["report_data"])

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

        return [_load_report(row["report_data"]) for row in rows]

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

        return [_load_report(row["report_data"]) for row in rows]


@lru_cache
def get_assessment_repository() -> SQLiteAssessmentRepository:
    return SQLiteAssessmentRepository(settings.storage.assessments_db_path)
