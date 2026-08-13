from __future__ import annotations

import pytest

from scalescore.core.async_assessment import BrokerAsyncAssessmentWorker


class FakeBroker:
    def __init__(self, job_id: str | None = "job-1") -> None:
        self.job_id = job_id
        self.acknowledged: list[str] = []
        self.requeued: list[str] = []
        self.recovered = 0

    def enqueue(self, job_id: str) -> None:
        raise AssertionError("enqueue should not be called by worker")

    def dequeue(self, *, timeout_seconds: int) -> str | None:
        return self.job_id

    def acknowledge(self, job_id: str) -> None:
        self.acknowledged.append(job_id)

    def requeue_reserved(self, job_id: str) -> None:
        self.requeued.append(job_id)

    def recover_stale_reservations(self) -> int:
        self.recovered += 1
        return self.recovered


class FakeWorker:
    def __init__(self, *, result: bool = True, raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.processed: list[str] = []
        self.requeued_processing_jobs = 0

    def requeue_processing_jobs(self) -> int:
        self.requeued_processing_jobs += 1
        return 0

    async def process_job(self, *, job_id: str) -> bool:
        self.processed.append(job_id)
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.mark.asyncio
async def test_broker_worker_acknowledges_successful_reservation() -> None:
    broker = FakeBroker("job-1")
    worker = FakeWorker(result=True)
    runtime = BrokerAsyncAssessmentWorker(
        broker=broker,
        worker=worker,
        dequeue_timeout_seconds=1,
    )

    processed = await runtime.process_next_enqueued_job()

    assert processed is True
    assert worker.processed == ["job-1"]
    assert broker.acknowledged == ["job-1"]
    assert broker.requeued == []


@pytest.mark.asyncio
async def test_broker_worker_acknowledges_unclaimable_reservation() -> None:
    broker = FakeBroker("job-1")
    worker = FakeWorker(result=False)
    runtime = BrokerAsyncAssessmentWorker(
        broker=broker,
        worker=worker,
        dequeue_timeout_seconds=1,
    )

    processed = await runtime.process_next_enqueued_job()

    assert processed is True
    assert broker.acknowledged == ["job-1"]
    assert broker.requeued == []


@pytest.mark.asyncio
async def test_broker_worker_requeues_reservation_when_processing_raises() -> None:
    broker = FakeBroker("job-1")
    worker = FakeWorker(raises=RuntimeError("claim failed"))
    runtime = BrokerAsyncAssessmentWorker(
        broker=broker,
        worker=worker,
        dequeue_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match="claim failed"):
        await runtime.process_next_enqueued_job()

    assert broker.acknowledged == []
    assert broker.requeued == ["job-1"]


@pytest.mark.asyncio
async def test_broker_worker_recovers_stale_reservations_on_start() -> None:
    broker = FakeBroker(None)
    worker = FakeWorker()
    runtime = BrokerAsyncAssessmentWorker(
        broker=broker,
        worker=worker,
        dequeue_timeout_seconds=1,
        idle_sleep_seconds=0.01,
    )

    await runtime.start()
    await runtime.stop()

    assert worker.requeued_processing_jobs == 1
    assert broker.recovered == 1
