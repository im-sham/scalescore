from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scalescore.storage.async_assessment_repository import (
    AsyncAssessmentStatus,
    SQLiteAsyncAssessmentJobRepository,
)


def test_create_and_get_job(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    created = repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )

    assert created.job_id == "job_1"
    assert created.status == AsyncAssessmentStatus.QUEUED
    assert created.progress_stage == "queued"
    assert created.progress_percentage == 0

    loaded = repository.get_job("job_1", tenant_id="tenant_1")
    assert loaded is not None
    assert loaded.job_id == "job_1"
    assert loaded.tenant_id == "tenant_1"


def test_claim_marks_job_processing(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )

    claimed = repository.claim_next_queued_job()
    assert claimed is not None
    assert claimed.status == AsyncAssessmentStatus.PROCESSING
    assert claimed.progress_stage == "processing"
    assert claimed.progress_percentage == 10
    assert claimed.started_at is not None


def test_claim_job_by_id_marks_job_processing(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.create_job(
        job_id="job_2",
        tenant_id="tenant_1",
        submitted_by="user_2",
        dataset_path="/tmp/dataset-2",
    )

    claimed = repository.claim_job(job_id="job_2")
    assert claimed is not None
    assert claimed.job_id == "job_2"
    assert claimed.status == AsyncAssessmentStatus.PROCESSING

    next_claimed = repository.claim_next_queued_job()
    assert next_claimed is not None
    assert next_claimed.job_id == "job_1"


def test_mark_completed_updates_report_metadata(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.claim_next_queued_job()

    completed = repository.mark_completed(
        job_id="job_1",
        report_id="report_1",
        org_id="org_1",
    )
    assert completed is not None
    assert completed.status == AsyncAssessmentStatus.COMPLETED
    assert completed.progress_stage == "completed"
    assert completed.progress_percentage == 100
    assert completed.report_id == "report_1"
    assert completed.org_id == "org_1"
    assert completed.completed_at is not None


def test_requeue_processing_jobs(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    claimed_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.claim_next_queued_job(
        worker_id="worker-a",
        lease_seconds=60,
        now=claimed_at,
    )

    requeued_count = repository.requeue_processing_jobs(
        now=claimed_at + timedelta(seconds=61),
    )
    assert requeued_count == 1

    reloaded = repository.get_job("job_1", tenant_id="tenant_1")
    assert reloaded is not None
    assert reloaded.status == AsyncAssessmentStatus.QUEUED
    assert reloaded.progress_stage == "queued"
    assert reloaded.progress_percentage == 0
    assert reloaded.started_at is None


def test_requeue_processing_jobs_preserves_active_lease(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    claimed_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    claimed = repository.claim_next_queued_job(
        worker_id="worker-a",
        lease_seconds=60,
        now=claimed_at,
    )
    assert claimed is not None
    assert claimed.claimed_by == "worker-a"
    assert claimed.lease_expires_at == claimed_at + timedelta(seconds=60)

    requeued_count = repository.requeue_processing_jobs(
        now=claimed_at + timedelta(seconds=30),
    )
    assert requeued_count == 0

    reloaded = repository.get_job("job_1", tenant_id="tenant_1")
    assert reloaded is not None
    assert reloaded.status == AsyncAssessmentStatus.PROCESSING
    assert reloaded.claimed_by == "worker-a"


def test_count_jobs_filters_by_status(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.create_job(
        job_id="job_2",
        tenant_id="tenant_1",
        submitted_by="user_2",
        dataset_path="/tmp/dataset-2",
    )
    repository.create_job(
        job_id="job_3",
        tenant_id="tenant_2",
        submitted_by="user_3",
        dataset_path="/tmp/dataset-3",
    )
    repository.claim_job(job_id="job_1")

    tenant_1_total = repository.count_jobs(tenant_id="tenant_1")
    tenant_1_outstanding = repository.count_jobs(
        tenant_id="tenant_1",
        statuses={AsyncAssessmentStatus.QUEUED, AsyncAssessmentStatus.PROCESSING},
    )

    assert tenant_1_total == 2
    assert tenant_1_outstanding == 2


def test_update_progress_persists_stage_and_message(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    claimed_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.claim_job(
        job_id="job_1",
        worker_id="worker-a",
        lease_seconds=60,
        now=claimed_at,
    )

    progress = repository.update_progress(
        job_id="job_1",
        stage="processing",
        percentage=42,
        message="Crunching scoring model",
        worker_id="worker-a",
        lease_seconds=120,
        now=claimed_at + timedelta(seconds=30),
    )
    assert progress is not None
    assert progress.progress_stage == "processing"
    assert progress.progress_percentage == 42
    assert progress.progress_message == "Crunching scoring model"
    assert progress.heartbeat_at == claimed_at + timedelta(seconds=30)
    assert progress.lease_expires_at == claimed_at + timedelta(seconds=150)


def test_processing_updates_reject_non_owner(tmp_path: Path) -> None:
    repository = SQLiteAsyncAssessmentJobRepository(tmp_path / "assessments.sqlite3")
    claimed_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.create_job(
        job_id="job_1",
        tenant_id="tenant_1",
        submitted_by="user_1",
        dataset_path="/tmp/dataset",
    )
    repository.claim_job(
        job_id="job_1",
        worker_id="worker-a",
        lease_seconds=60,
        now=claimed_at,
    )

    progress = repository.update_progress(
        job_id="job_1",
        stage="processing",
        percentage=42,
        message="Wrong worker",
        worker_id="worker-b",
        lease_seconds=60,
        now=claimed_at + timedelta(seconds=5),
    )
    completed = repository.mark_completed(
        job_id="job_1",
        report_id="report_1",
        org_id="org_1",
        worker_id="worker-b",
    )

    assert progress is None
    assert completed is None
    reloaded = repository.get_job("job_1", tenant_id="tenant_1")
    assert reloaded is not None
    assert reloaded.status == AsyncAssessmentStatus.PROCESSING
    assert reloaded.claimed_by == "worker-a"
    assert reloaded.report_id is None
