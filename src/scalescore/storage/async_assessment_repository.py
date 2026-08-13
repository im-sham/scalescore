from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError
from scalescore.models.scaling import WorkflowAssessmentContext


class AsyncAssessmentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncAssessmentJob:
    job_id: str
    tenant_id: str
    submitted_by: str
    dataset_path: str
    workflow_context: WorkflowAssessmentContext | None
    status: AsyncAssessmentStatus
    progress_stage: str
    progress_percentage: int
    progress_message: str | None
    report_id: str | None
    org_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    claimed_by: str | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None


class AsyncAssessmentJobRepository(Protocol):
    def create_job(
        self,
        *,
        job_id: str,
        tenant_id: str,
        submitted_by: str,
        dataset_path: str,
        workflow_context: WorkflowAssessmentContext | None = None,
    ) -> AsyncAssessmentJob: ...

    def get_job(self, job_id: str, *, tenant_id: str) -> AsyncAssessmentJob | None: ...

    def claim_job(
        self,
        *,
        job_id: str,
        worker_id: str = "worker",
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None: ...

    def claim_next_queued_job(
        self,
        *,
        worker_id: str = "worker",
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None: ...

    def update_progress(
        self,
        *,
        job_id: str,
        stage: str,
        percentage: int,
        message: str | None,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None: ...

    def count_jobs(
        self,
        *,
        tenant_id: str,
        statuses: set[AsyncAssessmentStatus] | None = None,
    ) -> int: ...

    def mark_completed(
        self,
        *,
        job_id: str,
        report_id: str,
        org_id: str,
        worker_id: str | None = None,
    ) -> AsyncAssessmentJob | None: ...

    def mark_failed(
        self,
        *,
        job_id: str,
        error_message: str,
        worker_id: str | None = None,
    ) -> AsyncAssessmentJob | None: ...

    def requeue_processing_jobs(self, *, now: datetime | None = None) -> int: ...


class SQLiteAsyncAssessmentJobRepository:
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
                        CREATE TABLE IF NOT EXISTS async_assessment_jobs (
                            job_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            submitted_by TEXT NOT NULL,
                            dataset_path TEXT NOT NULL,
                            workflow_context_json TEXT,
                            status TEXT NOT NULL,
                            progress_stage TEXT NOT NULL DEFAULT 'queued',
                            progress_percentage INTEGER NOT NULL DEFAULT 0,
                            progress_message TEXT,
                            report_id TEXT,
                            org_id TEXT,
                            error_message TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            started_at TEXT,
                            completed_at TEXT,
                            claimed_by TEXT,
                            heartbeat_at TEXT,
                            lease_expires_at TEXT
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_async_jobs_tenant_created
                        ON async_assessment_jobs (tenant_id, created_at DESC)
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_async_jobs_status_created
                        ON async_assessment_jobs (status, created_at ASC)
                        """
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "workflow_context_json",
                        "TEXT",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "progress_stage",
                        "TEXT NOT NULL DEFAULT 'queued'",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "progress_percentage",
                        "INTEGER NOT NULL DEFAULT 0",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "progress_message",
                        "TEXT",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "claimed_by",
                        "TEXT",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "heartbeat_at",
                        "TEXT",
                    )
                    self._ensure_column(
                        connection,
                        "async_assessment_jobs",
                        "lease_expires_at",
                        "TEXT",
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize async assessment job storage", cause=err) from err

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
    def _status_value(status: AsyncAssessmentStatus | str) -> str:
        if isinstance(status, AsyncAssessmentStatus):
            return status.value
        return status

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _coerce_now(now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(UTC)
        return now.astimezone(UTC)

    @staticmethod
    def _lease_expires_at(now: datetime, lease_seconds: int) -> datetime:
        return now + timedelta(seconds=max(1, lease_seconds))

    @staticmethod
    def _worker_id_value(worker_id: str) -> str:
        normalized = worker_id.strip()
        return normalized[:255] if normalized else "worker"

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
            raise DatabaseError("Stored async workflow context is invalid", cause=err) from err

    def _row_to_job(self, row: sqlite3.Row) -> AsyncAssessmentJob:
        return AsyncAssessmentJob(
            job_id=row["job_id"],
            tenant_id=row["tenant_id"],
            submitted_by=row["submitted_by"],
            dataset_path=row["dataset_path"],
            workflow_context=self._parse_workflow_context(row["workflow_context_json"]),
            status=AsyncAssessmentStatus(row["status"]),
            progress_stage=row["progress_stage"],
            progress_percentage=int(row["progress_percentage"]),
            progress_message=row["progress_message"],
            report_id=row["report_id"],
            org_id=row["org_id"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            claimed_by=row["claimed_by"],
            heartbeat_at=self._parse_datetime(row["heartbeat_at"]),
            lease_expires_at=self._parse_datetime(row["lease_expires_at"]),
        )

    def create_job(
        self,
        *,
        job_id: str,
        tenant_id: str,
        submitted_by: str,
        dataset_path: str,
        workflow_context: WorkflowAssessmentContext | None = None,
    ) -> AsyncAssessmentJob:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO async_assessment_jobs (
                            job_id,
                            tenant_id,
                            submitted_by,
                            dataset_path,
                            workflow_context_json,
                            status,
                            progress_stage,
                            progress_percentage,
                            progress_message,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            tenant_id,
                            submitted_by,
                            dataset_path,
                            self._serialize_workflow_context(workflow_context),
                            AsyncAssessmentStatus.QUEUED.value,
                            "queued",
                            0,
                            "Queued for processing",
                            now,
                            now,
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to create async assessment job", cause=err) from err

        created = self.get_job(job_id, tenant_id=tenant_id)
        if created is None:
            raise DatabaseError("Async assessment job was not persisted")
        return created

    def get_job(self, job_id: str, *, tenant_id: str) -> AsyncAssessmentJob | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT job_id, tenant_id, submitted_by, dataset_path,
                           workflow_context_json, status, progress_stage,
                           progress_percentage, progress_message, report_id, org_id,
                           error_message, created_at, updated_at, started_at,
                           completed_at, claimed_by, heartbeat_at, lease_expires_at
                    FROM async_assessment_jobs
                    WHERE job_id = ? AND tenant_id = ?
                    """,
                    (job_id, tenant_id),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load async assessment job", cause=err) from err

        if row is None:
            return None
        return self._row_to_job(row)

    def claim_job(
        self,
        *,
        job_id: str,
        worker_id: str = "worker",
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None:
        claimed_at = self._coerce_now(now)
        claimed_at_iso = claimed_at.isoformat()
        lease_expires_at = self._lease_expires_at(claimed_at, lease_seconds).isoformat()
        claimed_by = self._worker_id_value(worker_id)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT tenant_id
                        FROM async_assessment_jobs
                        WHERE job_id = ? AND status = ?
                        """,
                        (job_id, AsyncAssessmentStatus.QUEUED.value),
                    ).fetchone()
                    if row is None:
                        return None

                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = ?, updated_at = ?,
                            error_message = NULL, claimed_by = ?, heartbeat_at = ?,
                            lease_expires_at = ?
                        WHERE job_id = ? AND status = ?
                        """,
                        (
                            AsyncAssessmentStatus.PROCESSING.value,
                            "processing",
                            10,
                            "Job claimed by worker",
                            claimed_at_iso,
                            claimed_at_iso,
                            claimed_by,
                            claimed_at_iso,
                            lease_expires_at,
                            job_id,
                            AsyncAssessmentStatus.QUEUED.value,
                        ),
                    )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to claim async assessment job", cause=err) from err

        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def claim_next_queued_job(
        self,
        *,
        worker_id: str = "worker",
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None:
        claimed_at = self._coerce_now(now)
        claimed_at_iso = claimed_at.isoformat()
        lease_expires_at = self._lease_expires_at(claimed_at, lease_seconds).isoformat()
        claimed_by = self._worker_id_value(worker_id)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT job_id, tenant_id
                        FROM async_assessment_jobs
                        WHERE status = ?
                        ORDER BY created_at ASC
                        LIMIT 1
                        """,
                        (AsyncAssessmentStatus.QUEUED.value,),
                    ).fetchone()
                    if row is None:
                        return None

                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = ?, updated_at = ?,
                            error_message = NULL, claimed_by = ?, heartbeat_at = ?,
                            lease_expires_at = ?
                        WHERE job_id = ? AND tenant_id = ? AND status = ?
                        """,
                        (
                            AsyncAssessmentStatus.PROCESSING.value,
                            "processing",
                            10,
                            "Job claimed by worker",
                            claimed_at_iso,
                            claimed_at_iso,
                            claimed_by,
                            claimed_at_iso,
                            lease_expires_at,
                            row["job_id"],
                            row["tenant_id"],
                            AsyncAssessmentStatus.QUEUED.value,
                        ),
                    )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to claim async assessment job", cause=err) from err

        return self.get_job(row["job_id"], tenant_id=row["tenant_id"])

    def count_jobs(
        self,
        *,
        tenant_id: str,
        statuses: set[AsyncAssessmentStatus] | None = None,
    ) -> int:
        query = "SELECT COUNT(1) AS count FROM async_assessment_jobs WHERE tenant_id = ?"
        params: list[str] = [tenant_id]

        if statuses:
            status_values = [self._status_value(status) for status in statuses]
            placeholders = ", ".join("?" for _ in status_values)
            query = f"{query} AND status IN ({placeholders})"
            params.extend(status_values)

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(query, params).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to count async assessment jobs", cause=err) from err

        if row is None:
            return 0
        return int(row["count"])

    def update_progress(
        self,
        *,
        job_id: str,
        stage: str,
        percentage: int,
        message: str | None,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> AsyncAssessmentJob | None:
        bounded_percentage = max(0, min(100, percentage))
        clipped_message = message.strip()[:500] if message else None
        updated_at = self._coerce_now(now)
        updated_at_iso = updated_at.isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    if worker_id is not None:
                        lease_expires_at = self._lease_expires_at(
                            updated_at, lease_seconds
                        ).isoformat()
                        result = connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET progress_stage = ?, progress_percentage = ?,
                                progress_message = ?, updated_at = ?, heartbeat_at = ?,
                                lease_expires_at = ?
                            WHERE job_id = ? AND status = ? AND claimed_by = ?
                            """,
                            (
                                stage.strip() or "processing",
                                bounded_percentage,
                                clipped_message,
                                updated_at_iso,
                                updated_at_iso,
                                lease_expires_at,
                                job_id,
                                AsyncAssessmentStatus.PROCESSING.value,
                                self._worker_id_value(worker_id),
                            ),
                        )
                        if result.rowcount == 0:
                            return None
                    else:
                        connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET progress_stage = ?, progress_percentage = ?,
                                progress_message = ?, updated_at = ?
                            WHERE job_id = ?
                            """,
                            (
                                stage.strip() or "processing",
                                bounded_percentage,
                                clipped_message,
                                updated_at_iso,
                                job_id,
                            ),
                        )
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM async_assessment_jobs WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to update async assessment progress", cause=err) from err

        if row is None:
            return None
        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def mark_completed(
        self,
        *,
        job_id: str,
        report_id: str,
        org_id: str,
        worker_id: str | None = None,
    ) -> AsyncAssessmentJob | None:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM async_assessment_jobs WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchone()
                    if row is None:
                        return None
                    if worker_id is not None:
                        result = connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET status = ?, progress_stage = ?, progress_percentage = ?,
                                progress_message = ?, report_id = ?, org_id = ?,
                                completed_at = ?, updated_at = ?, claimed_by = NULL,
                                heartbeat_at = NULL, lease_expires_at = NULL
                            WHERE job_id = ? AND status = ? AND claimed_by = ?
                            """,
                            (
                                AsyncAssessmentStatus.COMPLETED.value,
                                "completed",
                                100,
                                "Assessment completed",
                                report_id,
                                org_id,
                                now,
                                now,
                                job_id,
                                AsyncAssessmentStatus.PROCESSING.value,
                                self._worker_id_value(worker_id),
                            ),
                        )
                    else:
                        result = connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET status = ?, progress_stage = ?, progress_percentage = ?,
                                progress_message = ?, report_id = ?, org_id = ?,
                                completed_at = ?, updated_at = ?, claimed_by = NULL,
                                heartbeat_at = NULL, lease_expires_at = NULL
                            WHERE job_id = ?
                            """,
                            (
                                AsyncAssessmentStatus.COMPLETED.value,
                                "completed",
                                100,
                                "Assessment completed",
                                report_id,
                                org_id,
                                now,
                                now,
                                job_id,
                            ),
                        )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to mark async assessment job as completed", cause=err) from err

        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def mark_failed(
        self,
        *,
        job_id: str,
        error_message: str,
        worker_id: str | None = None,
    ) -> AsyncAssessmentJob | None:
        now = datetime.now(UTC).isoformat()
        clipped_error = error_message.strip()[:500]
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM async_assessment_jobs WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchone()
                    if row is None:
                        return None
                    if worker_id is not None:
                        result = connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET status = ?, progress_stage = ?, progress_message = ?,
                                error_message = ?, completed_at = ?, updated_at = ?,
                                claimed_by = NULL, heartbeat_at = NULL,
                                lease_expires_at = NULL
                            WHERE job_id = ? AND status = ? AND claimed_by = ?
                            """,
                            (
                                AsyncAssessmentStatus.FAILED.value,
                                "failed",
                                clipped_error,
                                clipped_error,
                                now,
                                now,
                                job_id,
                                AsyncAssessmentStatus.PROCESSING.value,
                                self._worker_id_value(worker_id),
                            ),
                        )
                    else:
                        result = connection.execute(
                            """
                            UPDATE async_assessment_jobs
                            SET status = ?, progress_stage = ?, progress_message = ?,
                                error_message = ?, completed_at = ?, updated_at = ?,
                                claimed_by = NULL, heartbeat_at = NULL,
                                lease_expires_at = NULL
                            WHERE job_id = ?
                            """,
                            (
                                AsyncAssessmentStatus.FAILED.value,
                                "failed",
                                clipped_error,
                                clipped_error,
                                now,
                                now,
                                job_id,
                            ),
                        )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to mark async assessment job as failed", cause=err) from err

        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def requeue_processing_jobs(self, *, now: datetime | None = None) -> int:
        now_iso = self._coerce_now(now).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = NULL, updated_at = ?,
                            claimed_by = NULL, heartbeat_at = NULL,
                            lease_expires_at = NULL
                        WHERE status = ?
                          AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                        """,
                        (
                            AsyncAssessmentStatus.QUEUED.value,
                            "queued",
                            0,
                            "Requeued after worker restart",
                            now_iso,
                            AsyncAssessmentStatus.PROCESSING.value,
                            now_iso,
                        ),
                    )
                    return result.rowcount
        except sqlite3.Error as err:
            raise DatabaseError("Failed to requeue processing jobs", cause=err) from err


@lru_cache
def get_async_assessment_job_repository() -> SQLiteAsyncAssessmentJobRepository:
    return SQLiteAsyncAssessmentJobRepository(settings.storage.assessments_db_path)
