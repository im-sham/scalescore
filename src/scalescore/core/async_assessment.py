from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Protocol

from scalescore.core.assessment import run_assessment_from_csv
from scalescore.core.audit import audit_assessment_created
from scalescore.core.logging import get_logger
from scalescore.storage.assessment_repository import AssessmentRepository
from scalescore.storage.async_assessment_repository import (
    AsyncAssessmentJob,
    AsyncAssessmentJobRepository,
)

logger = get_logger(__name__)


class AsyncAssessmentQueueBroker(Protocol):
    def enqueue(self, job_id: str) -> None: ...

    def dequeue(self, *, timeout_seconds: int) -> str | None: ...


class AsyncAssessmentWorker:
    """Background worker that processes queued async assessment jobs."""

    def __init__(
        self,
        *,
        job_repository: AsyncAssessmentJobRepository,
        assessment_repository: AssessmentRepository,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self._job_repository = job_repository
        self._assessment_repository = assessment_repository
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        requeued = self.requeue_processing_jobs()
        if requeued:
            logger.warning(
                "async_assessment_jobs_requeued",
                count=requeued,
            )
        self._task = asyncio.create_task(
            self._run(),
            name="scalescore-async-assessment-worker",
        )
        logger.info(
            "async_assessment_worker_started",
            poll_interval_seconds=self._poll_interval_seconds,
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
            logger.info("async_assessment_worker_stopped")

    async def _run(self) -> None:
        while True:
            claimed = await self.process_next_job()
            if not claimed:
                await asyncio.sleep(self._poll_interval_seconds)

    async def process_next_job(self) -> bool:
        job = self._job_repository.claim_next_queued_job()
        if job is None:
            return False
        await self._process_job(job)
        return True

    async def process_job(self, *, job_id: str) -> bool:
        job = self._job_repository.claim_job(job_id=job_id)
        if job is None:
            logger.info(
                "async_assessment_job_not_claimed",
                job_id=job_id,
            )
            return False
        await self._process_job(job)
        return True

    def requeue_processing_jobs(self) -> int:
        return self._job_repository.requeue_processing_jobs()

    async def _process_job(self, job: AsyncAssessmentJob) -> None:
        dataset_path = Path(job.dataset_path)
        logger.info(
            "async_assessment_job_started",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            submitted_by=job.submitted_by,
        )

        try:
            self._job_repository.update_progress(
                job_id=job.job_id,
                stage="processing",
                percentage=30,
                message="Running assessment engine",
            )
            report = await asyncio.to_thread(run_assessment_from_csv, dataset_path)
            self._job_repository.update_progress(
                job_id=job.job_id,
                stage="processing",
                percentage=85,
                message="Persisting assessment report",
            )
            self._assessment_repository.save_report(report, tenant_id=job.tenant_id)
            self._job_repository.mark_completed(
                job_id=job.job_id,
                report_id=report.report_id,
                org_id=report.org_id,
            )
            audit_assessment_created(
                user_id=job.submitted_by,
                tenant_id=job.tenant_id,
                assessment_id=report.report_id,
                organization_id=report.org_id,
            )
            logger.info(
                "async_assessment_job_completed",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                report_id=report.report_id,
                org_id=report.org_id,
            )
        except Exception as err:  # noqa: BLE001
            self._job_repository.mark_failed(job_id=job.job_id, error_message=str(err))
            logger.exception(
                "async_assessment_job_failed",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                error_type=type(err).__name__,
            )
        finally:
            if dataset_path.exists():
                shutil.rmtree(dataset_path, ignore_errors=True)


class BrokerAsyncAssessmentWorker:
    """Worker loop that consumes queued job IDs from a broker and processes them."""

    def __init__(
        self,
        *,
        broker: AsyncAssessmentQueueBroker,
        worker: AsyncAssessmentWorker,
        dequeue_timeout_seconds: int = 5,
        idle_sleep_seconds: float = 0.05,
    ) -> None:
        self._broker = broker
        self._worker = worker
        self._dequeue_timeout_seconds = dequeue_timeout_seconds
        self._idle_sleep_seconds = idle_sleep_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        requeued = self._worker.requeue_processing_jobs()
        if requeued:
            logger.warning(
                "async_assessment_jobs_requeued",
                count=requeued,
            )
        self._task = asyncio.create_task(
            self._run(),
            name="scalescore-broker-async-assessment-worker",
        )
        logger.info(
            "broker_async_assessment_worker_started",
            dequeue_timeout_seconds=self._dequeue_timeout_seconds,
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
            logger.info("broker_async_assessment_worker_stopped")

    async def process_next_enqueued_job(self) -> bool:
        job_id = await asyncio.to_thread(
            self._broker.dequeue,
            timeout_seconds=self._dequeue_timeout_seconds,
        )
        if job_id is None:
            return False
        await self._worker.process_job(job_id=job_id)
        return True

    async def _run(self) -> None:
        while True:
            processed = await self.process_next_enqueued_job()
            if not processed:
                await asyncio.sleep(self._idle_sleep_seconds)
