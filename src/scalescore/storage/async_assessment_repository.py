from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError


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


class AsyncAssessmentJobRepository(Protocol):
    def create_job(
        self,
        *,
        job_id: str,
        tenant_id: str,
        submitted_by: str,
        dataset_path: str,
    ) -> AsyncAssessmentJob: ...

    def get_job(self, job_id: str, *, tenant_id: str) -> AsyncAssessmentJob | None: ...

    def claim_job(self, *, job_id: str) -> AsyncAssessmentJob | None: ...

    def claim_next_queued_job(self) -> AsyncAssessmentJob | None: ...

    def update_progress(
        self,
        *,
        job_id: str,
        stage: str,
        percentage: int,
        message: str | None,
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
    ) -> AsyncAssessmentJob | None: ...

    def mark_failed(self, *, job_id: str, error_message: str) -> AsyncAssessmentJob | None: ...

    def requeue_processing_jobs(self) -> int: ...


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
                            completed_at TEXT
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

    def _row_to_job(self, row: sqlite3.Row) -> AsyncAssessmentJob:
        return AsyncAssessmentJob(
            job_id=row["job_id"],
            tenant_id=row["tenant_id"],
            submitted_by=row["submitted_by"],
            dataset_path=row["dataset_path"],
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
        )

    def create_job(
        self,
        *,
        job_id: str,
        tenant_id: str,
        submitted_by: str,
        dataset_path: str,
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
                            status,
                            progress_stage,
                            progress_percentage,
                            progress_message,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            tenant_id,
                            submitted_by,
                            dataset_path,
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
                    SELECT job_id, tenant_id, submitted_by, dataset_path, status, progress_stage,
                           progress_percentage, progress_message, report_id, org_id,
                           error_message, created_at, updated_at, started_at, completed_at
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

    def claim_job(self, *, job_id: str) -> AsyncAssessmentJob | None:
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

                    now = datetime.now(UTC).isoformat()
                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = ?, updated_at = ?, error_message = NULL
                        WHERE job_id = ? AND status = ?
                        """,
                        (
                            AsyncAssessmentStatus.PROCESSING.value,
                            "processing",
                            10,
                            "Job claimed by worker",
                            now,
                            now,
                            job_id,
                            AsyncAssessmentStatus.QUEUED.value,
                        ),
                    )
                    if result.rowcount == 0:
                        return None
        except sqlite3.Error as err:
            raise DatabaseError("Failed to claim async assessment job", cause=err) from err

        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def claim_next_queued_job(self) -> AsyncAssessmentJob | None:
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

                    now = datetime.now(UTC).isoformat()
                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = ?, updated_at = ?, error_message = NULL
                        WHERE job_id = ? AND tenant_id = ? AND status = ?
                        """,
                        (
                            AsyncAssessmentStatus.PROCESSING.value,
                            "processing",
                            10,
                            "Job claimed by worker",
                            now,
                            now,
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
    ) -> AsyncAssessmentJob | None:
        bounded_percentage = max(0, min(100, percentage))
        clipped_message = message.strip()[:500] if message else None
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET progress_stage = ?, progress_percentage = ?, progress_message = ?, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            stage.strip() or "processing",
                            bounded_percentage,
                            clipped_message,
                            now,
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
    ) -> AsyncAssessmentJob | None:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, report_id = ?, org_id = ?, completed_at = ?,
                            updated_at = ?
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
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM async_assessment_jobs WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to mark async assessment job as completed", cause=err) from err

        if row is None:
            return None
        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def mark_failed(self, *, job_id: str, error_message: str) -> AsyncAssessmentJob | None:
        now = datetime.now(UTC).isoformat()
        clipped_error = error_message.strip()[:500]
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_message = ?,
                            error_message = ?, completed_at = ?, updated_at = ?
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
                    row = connection.execute(
                        """
                        SELECT tenant_id FROM async_assessment_jobs WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to mark async assessment job as failed", cause=err) from err

        if row is None:
            return None
        return self.get_job(job_id, tenant_id=row["tenant_id"])

    def requeue_processing_jobs(self) -> int:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    result = connection.execute(
                        """
                        UPDATE async_assessment_jobs
                        SET status = ?, progress_stage = ?, progress_percentage = ?,
                            progress_message = ?, started_at = NULL, updated_at = ?
                        WHERE status = ?
                        """,
                        (
                            AsyncAssessmentStatus.QUEUED.value,
                            "queued",
                            0,
                            "Requeued after worker restart",
                            now,
                            AsyncAssessmentStatus.PROCESSING.value,
                        ),
                    )
                    return result.rowcount
        except sqlite3.Error as err:
            raise DatabaseError("Failed to requeue processing jobs", cause=err) from err


@lru_cache
def get_async_assessment_job_repository() -> SQLiteAsyncAssessmentJobRepository:
    return SQLiteAsyncAssessmentJobRepository(settings.storage.assessments_db_path)
