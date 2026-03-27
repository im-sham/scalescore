from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scalescore.config import settings
from scalescore.core.async_assessment import AsyncAssessmentWorker
from scalescore.core.scheduled_assessment import ScheduledAssessmentDispatcher
from scalescore.models.scaling import WorkflowAssessmentContext, WorkflowBlastRadius
from scalescore.storage.assessment_repository import SQLiteAssessmentRepository
from scalescore.storage.async_assessment_repository import (
    AsyncAssessmentStatus,
    SQLiteAsyncAssessmentJobRepository,
)
from scalescore.storage.scheduled_assessment_repository import (
    ScheduledAssessmentCadence,
    SQLiteScheduledAssessmentRepository,
)


def _write_dataset(tmp_path: Path) -> None:
    (tmp_path / "organizations.csv").write_text(
        "id,name,headcount_current,revenue_current,burn_rate_monthly,runway_months\n"
        "org_1,Acme,100,1000000,50000,18\n",
        encoding="utf-8",
    )
    (tmp_path / "teams.csv").write_text(
        "id,org_id,name,function,headcount_current,parent_team_id,manager_id\n"
        "team_1,org_1,Engineering,engineering,50,,mgr_1\n",
        encoding="utf-8",
    )
    (tmp_path / "systems.csv").write_text(
        "id,org_id,name,system_type,capacity_current,capacity_max,capacity_unit,is_critical,dependencies\n"
        "sys_1,org_1,CRM,crm,90,100,users,true,\n",
        encoding="utf-8",
    )
    (tmp_path / "vendors.csv").write_text(
        "id,org_id,name,vendor_type,annual_cost,is_critical,alternatives\n"
        "ven_1,org_1,AWS,saas,100000,true,Azure|GCP\n",
        encoding="utf-8",
    )
    (tmp_path / "facilities.csv").write_text(
        "id,org_id,name,facility_type,location,capacity_seats,capacity_used,lease_end_date\n"
        "fac_1,org_1,HQ,office,SF,100,90,2027-06-30\n",
        encoding="utf-8",
    )
    (tmp_path / "growth_signals.csv").write_text(
        "id,org_id,signal_type,title,target_date,magnitude,magnitude_type,confidence,affected_areas\n"
        "sig_1,org_1,headcount_plan,Scale,2026-12-31,100,percentage,0.8,engineering|operations\n",
        encoding="utf-8",
    )


def _workflow_context() -> WorkflowAssessmentContext:
    return WorkflowAssessmentContext(
        workflow_id="wf_support_triage",
        name="Support Triage",
        business_function="customer_support",
        owner="Head of Support",
        ai_role="ticket triage and routing",
        systems_touched=["sys_1", "ven_1"],
        human_escalation_path=["support_lead", "ops_manager"],
        control_requirements=["approval_trace", "decision_logs"],
        blast_radius=WorkflowBlastRadius.MEDIUM,
        fallback_mode="manual queue review",
        override_rights=["support_manager"],
        error_tolerance="low",
        reversibility="tickets can be re-routed manually",
    )


async def test_scheduled_dispatch_and_async_worker_preserve_workflow_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage_db = tmp_path / "assessments.sqlite3"
    monkeypatch.setattr(settings.storage, "assessments_db_path", str(storage_db))

    assessment_repository = SQLiteAssessmentRepository(storage_db)
    job_repository = SQLiteAsyncAssessmentJobRepository(storage_db)
    schedule_repository = SQLiteScheduledAssessmentRepository(storage_db)

    source_dataset = tmp_path / "scheduled-dataset"
    source_dataset.mkdir()
    _write_dataset(source_dataset)
    workflow_context = _workflow_context()

    schedule = schedule_repository.create_schedule(
        schedule_id="schedule_1",
        tenant_id="tenant_1",
        created_by="user_1",
        name="Daily Support Workflow",
        cadence=ScheduledAssessmentCadence.DAILY,
        run_hour_utc=0,
        run_minute_utc=0,
        run_day_of_week=None,
        dataset_path=str(source_dataset),
        workflow_context=workflow_context,
    )

    with sqlite3.connect(storage_db) as connection:
        connection.execute(
            """
            UPDATE scheduled_assessments
            SET next_run_at = ?
            WHERE schedule_id = ?
            """,
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), schedule.schedule_id),
        )
        connection.commit()

    dispatcher = ScheduledAssessmentDispatcher(
        schedule_repository=schedule_repository,
        job_repository=job_repository,
        dispatch_interval_seconds=0.1,
        dispatch_batch_size=5,
    )
    dispatched = await dispatcher.dispatch_due_schedules_once()
    assert dispatched == 1

    refreshed_schedule = schedule_repository.get_schedule("schedule_1", tenant_id="tenant_1")
    assert refreshed_schedule is not None
    assert refreshed_schedule.workflow_context is not None
    assert refreshed_schedule.workflow_context.workflow_id == workflow_context.workflow_id
    assert refreshed_schedule.last_job_id is not None

    queued_job = job_repository.get_job(refreshed_schedule.last_job_id, tenant_id="tenant_1")
    assert queued_job is not None
    assert queued_job.status == AsyncAssessmentStatus.QUEUED
    assert queued_job.workflow_context is not None
    assert queued_job.workflow_context.workflow_id == workflow_context.workflow_id

    worker = AsyncAssessmentWorker(
        job_repository=job_repository,
        assessment_repository=assessment_repository,
    )
    processed = await worker.process_job(job_id=queued_job.job_id)
    assert processed is True

    completed_job = job_repository.get_job(queued_job.job_id, tenant_id="tenant_1")
    assert completed_job is not None
    assert completed_job.status == AsyncAssessmentStatus.COMPLETED
    assert completed_job.report_id is not None
    assert not Path(completed_job.dataset_path).exists()

    report = assessment_repository.get_report(completed_job.report_id, tenant_id="tenant_1")
    assert report is not None
    assert report.assessment_mode == "workflow"
    assert report.workflow_context is not None
    assert report.workflow_context.workflow_id == workflow_context.workflow_id
    assert report.workflow_readiness_score is not None
