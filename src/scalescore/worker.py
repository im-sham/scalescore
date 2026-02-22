from __future__ import annotations

import argparse
import asyncio
import signal
from collections.abc import Callable

from scalescore.config import settings
from scalescore.core.async_assessment import AsyncAssessmentWorker, BrokerAsyncAssessmentWorker
from scalescore.core.async_broker import get_async_assessment_broker
from scalescore.core.logging import get_logger, setup_logging
from scalescore.core.scheduled_assessment import ScheduledAssessmentDispatcher
from scalescore.storage.assessment_repository import get_assessment_repository
from scalescore.storage.async_assessment_repository import get_async_assessment_job_repository
from scalescore.storage.scheduled_assessment_repository import get_scheduled_assessment_repository

logger = get_logger(__name__)


def _build_async_assessment_worker() -> AsyncAssessmentWorker:
    return AsyncAssessmentWorker(
        job_repository=get_async_assessment_job_repository(),
        assessment_repository=get_assessment_repository(),
        poll_interval_seconds=settings.async_assessment.worker_poll_interval_seconds,
    )


def _build_runtime_worker() -> AsyncAssessmentWorker | BrokerAsyncAssessmentWorker:
    base_worker = _build_async_assessment_worker()
    if settings.async_assessment.mode == "broker":
        return BrokerAsyncAssessmentWorker(
            broker=get_async_assessment_broker(),
            worker=base_worker,
            dequeue_timeout_seconds=settings.async_assessment.broker_dequeue_timeout_seconds,
        )
    return base_worker


def _build_scheduled_dispatcher() -> ScheduledAssessmentDispatcher | None:
    if not settings.features.enable_scheduled_assessments:
        return None
    enqueue_job = (
        (lambda job_id: get_async_assessment_broker().enqueue(job_id))
        if settings.async_assessment.mode == "broker"
        else None
    )
    return ScheduledAssessmentDispatcher(
        schedule_repository=get_scheduled_assessment_repository(),
        job_repository=get_async_assessment_job_repository(),
        enqueue_job=enqueue_job,
        dispatch_interval_seconds=settings.async_assessment.scheduled_dispatch_poll_interval_seconds,
        dispatch_batch_size=settings.async_assessment.scheduled_dispatch_batch_size,
    )


async def _run_once(
    worker: AsyncAssessmentWorker | BrokerAsyncAssessmentWorker,
    dispatcher: ScheduledAssessmentDispatcher | None,
) -> int:
    dispatched = 0
    if dispatcher is not None:
        dispatched = await dispatcher.dispatch_due_schedules_once()

    if isinstance(worker, BrokerAsyncAssessmentWorker):
        processed = await worker.process_next_enqueued_job()
    else:
        processed = await worker.process_next_job()
    return 0 if processed or dispatched > 0 else 1


def _install_signal_handlers(stop: Callable[[], None]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # pragma: no cover - platform-specific
            signal.signal(sig, lambda *_: stop())


async def _run_forever(
    worker: AsyncAssessmentWorker | BrokerAsyncAssessmentWorker,
    dispatcher: ScheduledAssessmentDispatcher | None,
) -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event.set)
    if dispatcher is not None:
        await dispatcher.start()
    await worker.start()
    logger.info(
        "async_worker_runtime_started",
        mode=settings.async_assessment.mode,
        scheduled_assessments_enabled=dispatcher is not None,
    )
    try:
        await stop_event.wait()
    finally:
        await worker.stop()
        if dispatcher is not None:
            await dispatcher.stop()
        logger.info("async_worker_runtime_stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scalescore-worker",
        description="Run async assessment queue workers.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job and exit",
    )
    return parser


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    if not settings.features.enable_async_assessments:
        parser.error("FEATURE_ENABLE_ASYNC_ASSESSMENTS must be true to run async worker")

    worker = _build_runtime_worker()
    dispatcher = _build_scheduled_dispatcher()
    if args.once:
        exit_code = asyncio.run(_run_once(worker, dispatcher))
        raise SystemExit(exit_code)

    asyncio.run(_run_forever(worker, dispatcher))


if __name__ == "__main__":
    main()
