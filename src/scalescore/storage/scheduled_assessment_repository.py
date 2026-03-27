from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError
from scalescore.models.scaling import WorkflowAssessmentContext


class ScheduledAssessmentStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class ScheduledAssessmentCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass
class ScheduledAssessment:
    schedule_id: str
    tenant_id: str
    created_by: str
    name: str
    status: ScheduledAssessmentStatus
    cadence: ScheduledAssessmentCadence
    run_hour_utc: int
    run_minute_utc: int
    run_day_of_week: int | None
    dataset_path: str
    workflow_context: WorkflowAssessmentContext | None
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    last_job_id: str | None
    last_error: str | None


class ScheduledAssessmentRepository(Protocol):
    def create_schedule(
        self,
        *,
        schedule_id: str,
        tenant_id: str,
        created_by: str,
        name: str,
        cadence: ScheduledAssessmentCadence,
        run_hour_utc: int,
        run_minute_utc: int,
        run_day_of_week: int | None,
        dataset_path: str,
        workflow_context: WorkflowAssessmentContext | None = None,
    ) -> ScheduledAssessment: ...

    def get_schedule(self, schedule_id: str, *, tenant_id: str) -> ScheduledAssessment | None: ...

    def list_schedules(
        self,
        *,
        tenant_id: str,
        status: ScheduledAssessmentStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScheduledAssessment]: ...

    def update_status(
        self,
        *,
        schedule_id: str,
        tenant_id: str,
        status: ScheduledAssessmentStatus,
    ) -> ScheduledAssessment | None: ...

    def claim_due_schedules(self, *, now: datetime, limit: int = 20) -> list[ScheduledAssessment]: ...

    def mark_run_dispatched(self, *, schedule_id: str, job_id: str) -> ScheduledAssessment | None: ...

    def mark_run_error(
        self,
        *,
        schedule_id: str,
        error_message: str,
    ) -> ScheduledAssessment | None: ...


class SQLiteScheduledAssessmentRepository:
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
                        CREATE TABLE IF NOT EXISTS scheduled_assessments (
                            schedule_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            created_by TEXT NOT NULL,
                            name TEXT NOT NULL,
                            status TEXT NOT NULL,
                            cadence TEXT NOT NULL,
                            run_hour_utc INTEGER NOT NULL,
                            run_minute_utc INTEGER NOT NULL,
                            run_day_of_week INTEGER,
                            dataset_path TEXT NOT NULL,
                            workflow_context_json TEXT,
                            next_run_at TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            last_run_at TEXT,
                            last_job_id TEXT,
                            last_error TEXT
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_scheduled_assessments_tenant_next_run
                        ON scheduled_assessments (tenant_id, status, next_run_at ASC)
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_scheduled_assessments_due
                        ON scheduled_assessments (status, next_run_at ASC)
                        """
                    )
                    self._ensure_column(
                        connection,
                        "scheduled_assessments",
                        "workflow_context_json",
                        "TEXT",
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize scheduled assessment storage", cause=err) from err

    @staticmethod
    def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if self._column_exists(connection, table, column):
            return
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _clip_error(message: str) -> str:
        return message.strip()[:500]

    @staticmethod
    def _serialize_workflow_context(
        workflow_context: WorkflowAssessmentContext | None,
    ) -> str | None:
        if workflow_context is None:
            return None
        return workflow_context.model_dump_json()

    @staticmethod
    def _parse_workflow_context(value: str | None) -> WorkflowAssessmentContext | None:
        if value is None:
            return None
        try:
            return WorkflowAssessmentContext.model_validate_json(value)
        except ValidationError as err:
            raise DatabaseError("Stored scheduled workflow context is invalid", cause=err) from err

    @staticmethod
    def _compute_next_run_at(
        *,
        now: datetime,
        cadence: ScheduledAssessmentCadence,
        run_hour_utc: int,
        run_minute_utc: int,
        run_day_of_week: int | None,
    ) -> datetime:
        reference = now.astimezone(UTC)
        candidate = datetime.combine(
            reference.date(),
            time(hour=run_hour_utc, minute=run_minute_utc, tzinfo=UTC),
        )

        if cadence == ScheduledAssessmentCadence.DAILY:
            if candidate <= reference:
                candidate += timedelta(days=1)
            return candidate

        if run_day_of_week is None:
            raise ValueError("run_day_of_week is required for weekly cadence")
        days_ahead = (run_day_of_week - reference.weekday()) % 7
        candidate = datetime.combine(
            reference.date() + timedelta(days=days_ahead),
            time(hour=run_hour_utc, minute=run_minute_utc, tzinfo=UTC),
        )
        if candidate <= reference:
            candidate += timedelta(days=7)
        return candidate

    def _row_to_schedule(self, row: sqlite3.Row) -> ScheduledAssessment:
        return ScheduledAssessment(
            schedule_id=row["schedule_id"],
            tenant_id=row["tenant_id"],
            created_by=row["created_by"],
            name=row["name"],
            status=ScheduledAssessmentStatus(row["status"]),
            cadence=ScheduledAssessmentCadence(row["cadence"]),
            run_hour_utc=int(row["run_hour_utc"]),
            run_minute_utc=int(row["run_minute_utc"]),
            run_day_of_week=row["run_day_of_week"],
            dataset_path=row["dataset_path"],
            workflow_context=self._parse_workflow_context(row["workflow_context_json"]),
            next_run_at=datetime.fromisoformat(row["next_run_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_run_at=self._parse_datetime(row["last_run_at"]),
            last_job_id=row["last_job_id"],
            last_error=row["last_error"],
        )

    def create_schedule(
        self,
        *,
        schedule_id: str,
        tenant_id: str,
        created_by: str,
        name: str,
        cadence: ScheduledAssessmentCadence,
        run_hour_utc: int,
        run_minute_utc: int,
        run_day_of_week: int | None,
        dataset_path: str,
        workflow_context: WorkflowAssessmentContext | None = None,
    ) -> ScheduledAssessment:
        if cadence == ScheduledAssessmentCadence.WEEKLY and run_day_of_week is None:
            raise ValueError("run_day_of_week is required when cadence is weekly")
        if run_day_of_week is not None and not 0 <= run_day_of_week <= 6:
            raise ValueError("run_day_of_week must be between 0 (Monday) and 6 (Sunday)")

        now = datetime.now(UTC)
        next_run_at = self._compute_next_run_at(
            now=now,
            cadence=cadence,
            run_hour_utc=run_hour_utc,
            run_minute_utc=run_minute_utc,
            run_day_of_week=run_day_of_week,
        )
        now_iso = now.isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO scheduled_assessments (
                            schedule_id,
                            tenant_id,
                            created_by,
                            name,
                            status,
                            cadence,
                            run_hour_utc,
                            run_minute_utc,
                            run_day_of_week,
                            dataset_path,
                            workflow_context_json,
                            next_run_at,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            schedule_id,
                            tenant_id,
                            created_by,
                            name.strip(),
                            ScheduledAssessmentStatus.ACTIVE.value,
                            cadence.value,
                            run_hour_utc,
                            run_minute_utc,
                            run_day_of_week,
                            dataset_path,
                            self._serialize_workflow_context(workflow_context),
                            next_run_at.isoformat(),
                            now_iso,
                            now_iso,
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to create scheduled assessment", cause=err) from err

        created = self.get_schedule(schedule_id, tenant_id=tenant_id)
        if created is None:
            raise DatabaseError("Scheduled assessment was not persisted")
        return created

    def get_schedule(self, schedule_id: str, *, tenant_id: str) -> ScheduledAssessment | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT schedule_id, tenant_id, created_by, name, status, cadence, run_hour_utc,
                           run_minute_utc, run_day_of_week, dataset_path, workflow_context_json,
                           next_run_at, created_at, updated_at, last_run_at, last_job_id, last_error
                    FROM scheduled_assessments
                    WHERE schedule_id = ? AND tenant_id = ?
                    """,
                    (schedule_id, tenant_id),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load scheduled assessment", cause=err) from err

        if row is None:
            return None
        return self._row_to_schedule(row)

    def list_schedules(
        self,
        *,
        tenant_id: str,
        status: ScheduledAssessmentStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScheduledAssessment]:
        query = """
            SELECT schedule_id, tenant_id, created_by, name, status, cadence, run_hour_utc,
                   run_minute_utc, run_day_of_week, dataset_path, workflow_context_json,
                   next_run_at, created_at, updated_at, last_run_at, last_job_id, last_error
            FROM scheduled_assessments
            WHERE tenant_id = ?
        """
        params: list[str | int] = [tenant_id]
        if status is not None:
            query = f"{query} AND status = ?"
            params.append(status.value)
        query = f"{query} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query, params).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to list scheduled assessments", cause=err) from err

        return [self._row_to_schedule(row) for row in rows]

    def update_status(
        self,
        *,
        schedule_id: str,
        tenant_id: str,
        status: ScheduledAssessmentStatus,
    ) -> ScheduledAssessment | None:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    if status == ScheduledAssessmentStatus.ACTIVE:
                        row = connection.execute(
                            """
                            SELECT cadence, run_hour_utc, run_minute_utc, run_day_of_week
                            FROM scheduled_assessments
                            WHERE schedule_id = ? AND tenant_id = ?
                            """,
                            (schedule_id, tenant_id),
                        ).fetchone()
                        if row is None:
                            return None
                        next_run_at = self._compute_next_run_at(
                            now=now,
                            cadence=ScheduledAssessmentCadence(row["cadence"]),
                            run_hour_utc=int(row["run_hour_utc"]),
                            run_minute_utc=int(row["run_minute_utc"]),
                            run_day_of_week=row["run_day_of_week"],
                        ).isoformat()
                        result = connection.execute(
                            """
                            UPDATE scheduled_assessments
                            SET status = ?, next_run_at = ?, updated_at = ?
                            WHERE schedule_id = ? AND tenant_id = ?
                            """,
                            (status.value, next_run_at, now_iso, schedule_id, tenant_id),
                        )
                    else:
                        result = connection.execute(
                            """
                            UPDATE scheduled_assessments
                            SET status = ?, updated_at = ?
                            WHERE schedule_id = ? AND tenant_id = ?
                            """,
                            (status.value, now_iso, schedule_id, tenant_id),
                        )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to update scheduled assessment status", cause=err) from err

        return self.get_schedule(schedule_id, tenant_id=tenant_id)

    def claim_due_schedules(self, *, now: datetime, limit: int = 20) -> list[ScheduledAssessment]:
        now_utc = now.astimezone(UTC)
        now_iso = now_utc.isoformat()
        claimed: list[ScheduledAssessment] = []
        try:
            with closing(self._connect()) as connection:
                with connection:
                    rows = connection.execute(
                        """
                        SELECT schedule_id, cadence, run_hour_utc, run_minute_utc, run_day_of_week, next_run_at
                        FROM scheduled_assessments
                        WHERE status = ? AND next_run_at <= ?
                        ORDER BY next_run_at ASC
                        LIMIT ?
                        """,
                        (ScheduledAssessmentStatus.ACTIVE.value, now_iso, limit),
                    ).fetchall()

                    for row in rows:
                        row_next_run_at = datetime.fromisoformat(row["next_run_at"])
                        reference = now_utc if now_utc > row_next_run_at else row_next_run_at
                        next_run = self._compute_next_run_at(
                            now=reference,
                            cadence=ScheduledAssessmentCadence(row["cadence"]),
                            run_hour_utc=int(row["run_hour_utc"]),
                            run_minute_utc=int(row["run_minute_utc"]),
                            run_day_of_week=row["run_day_of_week"],
                        )
                        result = connection.execute(
                            """
                            UPDATE scheduled_assessments
                            SET next_run_at = ?, last_run_at = ?, updated_at = ?, last_error = NULL
                            WHERE schedule_id = ? AND status = ? AND next_run_at = ?
                            """,
                            (
                                next_run.isoformat(),
                                now_iso,
                                now_iso,
                                row["schedule_id"],
                                ScheduledAssessmentStatus.ACTIVE.value,
                                row["next_run_at"],
                            ),
                        )
                        if result.rowcount == 0:
                            continue
                        claimed_row = connection.execute(
                            """
                            SELECT schedule_id, tenant_id, created_by, name, status, cadence, run_hour_utc,
                                   run_minute_utc, run_day_of_week, dataset_path, workflow_context_json,
                                   next_run_at, created_at, updated_at, last_run_at, last_job_id, last_error
                            FROM scheduled_assessments
                            WHERE schedule_id = ?
                            """,
                            (row["schedule_id"],),
                        ).fetchone()
                        if claimed_row is not None:
                            claimed.append(self._row_to_schedule(claimed_row))
        except sqlite3.Error as err:
            raise DatabaseError("Failed to claim due scheduled assessments", cause=err) from err

        return claimed

    def mark_run_dispatched(self, *, schedule_id: str, job_id: str) -> ScheduledAssessment | None:
        now_iso = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM scheduled_assessments WHERE schedule_id = ?
                        """,
                        (schedule_id,),
                    ).fetchone()
                    if row is None:
                        return None
                    connection.execute(
                        """
                        UPDATE scheduled_assessments
                        SET last_job_id = ?, last_error = NULL, updated_at = ?
                        WHERE schedule_id = ?
                        """,
                        (job_id, now_iso, schedule_id),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to persist scheduled assessment dispatch", cause=err) from err

        return self.get_schedule(schedule_id, tenant_id=row["tenant_id"])

    def mark_run_error(
        self,
        *,
        schedule_id: str,
        error_message: str,
    ) -> ScheduledAssessment | None:
        now_iso = datetime.now(UTC).isoformat()
        clipped = self._clip_error(error_message)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM scheduled_assessments WHERE schedule_id = ?
                        """,
                        (schedule_id,),
                    ).fetchone()
                    if row is None:
                        return None
                    connection.execute(
                        """
                        UPDATE scheduled_assessments
                        SET last_error = ?, updated_at = ?
                        WHERE schedule_id = ?
                        """,
                        (clipped, now_iso, schedule_id),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to persist scheduled assessment error", cause=err) from err

        return self.get_schedule(schedule_id, tenant_id=row["tenant_id"])


@lru_cache
def get_scheduled_assessment_repository() -> SQLiteScheduledAssessmentRepository:
    return SQLiteScheduledAssessmentRepository(settings.storage.assessments_db_path)
