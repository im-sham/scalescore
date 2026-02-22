from __future__ import annotations

from datetime import UTC, datetime
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


def test_claim_due_schedules_advances_next_run(tmp_path: Path) -> None:
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
    claimed = repository.claim_due_schedules(now=due_time, limit=5)
    assert len(claimed) == 1
    assert claimed[0].schedule_id == "schedule_1"
    assert claimed[0].next_run_at > due_time
    assert claimed[0].last_run_at is not None


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
