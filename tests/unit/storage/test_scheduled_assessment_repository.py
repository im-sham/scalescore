from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scalescore.storage.scheduled_assessment_repository import (
    ScheduledAssessmentCadence,
    ScheduledAssessmentStatus,
    SQLiteScheduledAssessmentRepository,
)


def test_create_and_get_scheduled_assessment(tmp_path: Path) -> None:
    repository = SQLiteScheduledAssessmentRepository(tmp_path / "assessments.sqlite3")
    created = repository.create_schedule(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        created_by="user_1",
        name="Daily Assessment",
        cadence=ScheduledAssessmentCadence.DAILY,
        run_hour_utc=5,
        run_minute_utc=15,
        run_day_of_week=None,
        dataset_path="/tmp/scheduled-dataset",
    )

    assert created.schedule_id == "schedule_1"
    assert created.status == ScheduledAssessmentStatus.ACTIVE
    assert created.cadence == ScheduledAssessmentCadence.DAILY
    assert created.next_run_at > datetime.now(UTC)

    loaded = repository.get_schedule("schedule_1", tenant_id="tenant_1")
    assert loaded is not None
    assert loaded.name == "Daily Assessment"


def test_claim_due_schedules_leases_without_advancing_next_run(tmp_path: Path) -> None:
    repository = SQLiteScheduledAssessmentRepository(tmp_path / "assessments.sqlite3")
    created = repository.create_schedule(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        created_by="user_1",
        name="Daily Assessment",
        cadence=ScheduledAssessmentCadence.DAILY,
        run_hour_utc=0,
        run_minute_utc=0,
        run_day_of_week=None,
        dataset_path="/tmp/scheduled-dataset",
    )

    due_time = created.next_run_at
    claimed = repository.claim_due_schedules(
        now=due_time,
        limit=5,
        dispatcher_id="dispatcher-a",
        lease_seconds=60,
    )
    assert len(claimed) == 1
    assert claimed[0].schedule_id == "schedule_1"
    assert claimed[0].next_run_at == due_time
    assert claimed[0].last_run_at is None
    assert claimed[0].dispatch_claimed_by == "dispatcher-a"
    assert claimed[0].dispatch_lease_expires_at == due_time + timedelta(seconds=60)

    second_claim = repository.claim_due_schedules(
        now=due_time + timedelta(seconds=30),
        limit=5,
        dispatcher_id="dispatcher-b",
        lease_seconds=60,
    )
    assert second_claim == []

    expired_claim = repository.claim_due_schedules(
        now=due_time + timedelta(seconds=61),
        limit=5,
        dispatcher_id="dispatcher-b",
        lease_seconds=60,
    )
    assert [schedule.schedule_id for schedule in expired_claim] == ["schedule_1"]
    assert expired_claim[0].dispatch_claimed_by == "dispatcher-b"


def test_mark_run_dispatched_advances_next_run_after_success(tmp_path: Path) -> None:
    repository = SQLiteScheduledAssessmentRepository(tmp_path / "assessments.sqlite3")
    created = repository.create_schedule(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        created_by="user_1",
        name="Daily Assessment",
        cadence=ScheduledAssessmentCadence.DAILY,
        run_hour_utc=0,
        run_minute_utc=0,
        run_day_of_week=None,
        dataset_path="/tmp/scheduled-dataset",
    )

    due_time = created.next_run_at
    repository.claim_due_schedules(
        now=due_time,
        limit=5,
        dispatcher_id="dispatcher-a",
        lease_seconds=60,
    )
    dispatched_at = due_time + timedelta(seconds=5)

    dispatched = repository.mark_run_dispatched(
        schedule_id="schedule_1",
        job_id="job_1",
        dispatched_at=dispatched_at,
        dispatcher_id="dispatcher-a",
    )

    assert dispatched is not None
    assert dispatched.last_job_id == "job_1"
    assert dispatched.last_run_at == dispatched_at
    assert dispatched.next_run_at > due_time
    assert dispatched.dispatch_claimed_by is None
    assert dispatched.dispatch_lease_expires_at is None


def test_pause_and_resume_scheduled_assessment(tmp_path: Path) -> None:
    repository = SQLiteScheduledAssessmentRepository(tmp_path / "assessments.sqlite3")
    repository.create_schedule(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        created_by="user_1",
        name="Weekly Assessment",
        cadence=ScheduledAssessmentCadence.WEEKLY,
        run_hour_utc=6,
        run_minute_utc=0,
        run_day_of_week=1,
        dataset_path="/tmp/scheduled-dataset",
    )

    paused = repository.update_status(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        status=ScheduledAssessmentStatus.PAUSED,
    )
    assert paused is not None
    assert paused.status == ScheduledAssessmentStatus.PAUSED

    resumed = repository.update_status(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        status=ScheduledAssessmentStatus.ACTIVE,
    )
    assert resumed is not None
    assert resumed.status == ScheduledAssessmentStatus.ACTIVE
    assert resumed.next_run_at > datetime.now(UTC)
