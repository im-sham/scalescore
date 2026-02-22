from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scalescore.config import settings
from scalescore.core.logging import get_logger
from scalescore.storage.async_assessment_repository import AsyncAssessmentJobRepository
from scalescore.storage.scheduled_assessment_repository import (
    ScheduledAssessment,
    ScheduledAssessmentRepository,
)

logger = get_logger(__name__)


def async_assessment_dataset_directory(job_id: str) -> Path:
    storage_root = Path(settings.storage.assessments_db_path).resolve().parent
    return storage_root / "async_assessment_jobs" / job_id


class ScheduledAssessmentDispatcher:
    """Dispatcher that creates async jobs for due scheduled assessments."""

    def __init__(
        self,
        *,
        schedule_repository: ScheduledAssessmentRepository,
        job_repository: AsyncAssessmentJobRepository,
        enqueue_job: Callable[[str], None] | None = None,
        dispatch_interval_seconds: float = 30.0,
        dispatch_batch_size: int = 10,
    ) -> None:
        self._schedule_repository = schedule_repository
        self._job_repository = job_repository
        self._enqueue_job = enqueue_job
        self._dispatch_interval_seconds = dispatch_interval_seconds
        self._dispatch_batch_size = dispatch_batch_size
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="scalescore-scheduled-assessment-dispatcher",
        )
        logger.info(
            "scheduled_assessment_dispatcher_started",
            dispatch_interval_seconds=self._dispatch_interval_seconds,
            dispatch_batch_size=self._dispatch_batch_size,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("scheduled_assessment_dispatcher_stopped")

    async def dispatch_due_schedules_once(self) -> int:
        now = datetime.now(UTC)
        schedules = await asyncio.to_thread(
            self._schedule_repository.claim_due_schedules,
            now=now,
            limit=self._dispatch_batch_size,
        )
        if not schedules:
            return 0

        dispatched_count = 0
        for schedule in schedules:
            dispatched = await self._dispatch_schedule(schedule)
            if dispatched:
                dispatched_count += 1
        return dispatched_count

    async def _run(self) -> None:
        while True:
            dispatched_count = await self.dispatch_due_schedules_once()
            if dispatched_count == 0:
                await asyncio.sleep(self._dispatch_interval_seconds)

    async def _dispatch_schedule(self, schedule: ScheduledAssessment) -> bool:
        source_dataset = Path(schedule.dataset_path).resolve()
        if not source_dataset.exists() or not source_dataset.is_dir():
            await asyncio.to_thread(
                self._schedule_repository.mark_run_error,
                schedule_id=schedule.schedule_id,
                error_message=(
                    f"Scheduled dataset path not found or invalid: {source_dataset}"
                ),
            )
            logger.warning(
                "scheduled_assessment_dataset_missing",
                schedule_id=schedule.schedule_id,
                tenant_id=schedule.tenant_id,
                dataset_path=str(source_dataset),
            )
            return False

        job_id = f"job_{uuid4().hex[:16]}"
        target_dataset = async_assessment_dataset_directory(job_id)
        try:
            await asyncio.to_thread(shutil.copytree, source_dataset, target_dataset)
            job = await asyncio.to_thread(
                self._job_repository.create_job,
                job_id=job_id,
                tenant_id=schedule.tenant_id,
                submitted_by=schedule.created_by,
                dataset_path=str(target_dataset),
            )

            if self._enqueue_job is not None:
                try:
                    await asyncio.to_thread(self._enqueue_job, job.job_id)
                except Exception as err:  # noqa: BLE001
                    await asyncio.to_thread(
                        self._job_repository.mark_failed,
                        job_id=job.job_id,
                        error_message=(
                            "Failed to enqueue scheduled async assessment job for broker processing"
                        ),
                    )
                    await asyncio.to_thread(
                        self._schedule_repository.mark_run_error,
                        schedule_id=schedule.schedule_id,
                        error_message=str(err),
                    )
                    shutil.rmtree(target_dataset, ignore_errors=True)
                    logger.exception(
                        "scheduled_assessment_enqueue_failed",
                        schedule_id=schedule.schedule_id,
                        tenant_id=schedule.tenant_id,
                        job_id=job.job_id,
                    )
                    return False

            await asyncio.to_thread(
                self._schedule_repository.mark_run_dispatched,
                schedule_id=schedule.schedule_id,
                job_id=job.job_id,
            )
            logger.info(
                "scheduled_assessment_dispatched",
                schedule_id=schedule.schedule_id,
                tenant_id=schedule.tenant_id,
                job_id=job.job_id,
            )
            return True
        except Exception as err:  # noqa: BLE001
            shutil.rmtree(target_dataset, ignore_errors=True)
            await asyncio.to_thread(
                self._schedule_repository.mark_run_error,
                schedule_id=schedule.schedule_id,
                error_message=str(err),
            )
            logger.exception(
                "scheduled_assessment_dispatch_failed",
                schedule_id=schedule.schedule_id,
                tenant_id=schedule.tenant_id,
            )
            return False
