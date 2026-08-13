from __future__ import annotations

import time
from functools import lru_cache

from scalescore.config import settings
from scalescore.core.async_assessment import AsyncAssessmentQueueBroker
from scalescore.core.exceptions import ConfigurationError


class AsyncAssessmentBrokerError(RuntimeError):
    """Raised when async broker operations fail."""


class RedisAsyncAssessmentBroker:
    """Redis list-backed broker for async assessment job IDs.

    Jobs move from the ready list to a processing list before DB claim. This
    makes a worker crash after reservation recoverable instead of losing the job
    ID from Redis entirely.
    """

    def __init__(
        self,
        *,
        url: str,
        queue_name: str,
        reservation_timeout_seconds: int,
    ) -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except ModuleNotFoundError as err:  # pragma: no cover - dependency check
            raise ConfigurationError(
                message=(
                    "redis dependency is required when ASYNC_ASSESSMENT_MODE=broker. "
                    "Install with: pip install 'redis>=5.0'"
                ),
                setting="ASYNC_ASSESSMENT_MODE",
            ) from err

        self._queue_name = queue_name
        self._processing_queue_name = f"{queue_name}:processing"
        self._reservation_timeout_seconds = reservation_timeout_seconds
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def enqueue(self, job_id: str) -> None:
        try:
            self._client.rpush(self._queue_name, job_id)
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to enqueue async assessment job into Redis broker"
            ) from err

    def dequeue(self, *, timeout_seconds: int) -> str | None:
        try:
            job_id = self._client.execute_command(
                "BLMOVE",
                self._queue_name,
                self._processing_queue_name,
                "LEFT",
                "RIGHT",
                timeout_seconds,
            )
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to dequeue async assessment job from Redis broker"
            ) from err

        if job_id is None:
            return None
        job_id = str(job_id)
        try:
            self._client.set(
                self._reservation_key(job_id),
                str(time.time()),
                ex=self._reservation_timeout_seconds * 2,
            )
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to mark async assessment broker reservation"
            ) from err
        return job_id

    def acknowledge(self, job_id: str) -> None:
        try:
            self._client.lrem(self._processing_queue_name, 1, job_id)
            self._client.delete(self._reservation_key(job_id))
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to acknowledge async assessment broker reservation"
            ) from err

    def requeue_reserved(self, job_id: str) -> None:
        try:
            removed = self._client.lrem(self._processing_queue_name, 1, job_id)
            if removed:
                self._client.rpush(self._queue_name, job_id)
            self._client.delete(self._reservation_key(job_id))
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to requeue async assessment broker reservation"
            ) from err

    def recover_stale_reservations(self) -> int:
        recovered = 0
        now = time.time()
        try:
            job_ids = self._client.lrange(self._processing_queue_name, 0, -1)
            for raw_job_id in job_ids:
                job_id = str(raw_job_id)
                reserved_at = self._reservation_started_at(job_id)
                if reserved_at is not None and (
                    now - reserved_at < self._reservation_timeout_seconds
                ):
                    continue
                removed = self._client.lrem(self._processing_queue_name, 1, job_id)
                if not removed:
                    continue
                self._client.rpush(self._queue_name, job_id)
                self._client.delete(self._reservation_key(job_id))
                recovered += 1
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to recover stale async assessment broker reservations"
            ) from err
        return recovered

    def _reservation_started_at(self, job_id: str) -> float | None:
        raw_value = self._client.get(self._reservation_key(job_id))
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except ValueError:
            return None

    def _reservation_key(self, job_id: str) -> str:
        return f"{self._processing_queue_name}:reservation:{job_id}"


@lru_cache
def get_async_assessment_broker() -> AsyncAssessmentQueueBroker:
    if settings.async_assessment.mode != "broker":
        raise ConfigurationError(
            message=(
                "Async assessment broker requested but ASYNC_ASSESSMENT_MODE is not 'broker'"
            ),
            setting="ASYNC_ASSESSMENT_MODE",
        )
    broker_url = settings.async_assessment.broker_url
    if not broker_url:
        raise ConfigurationError(
            message="ASYNC_ASSESSMENT_BROKER_URL is required when mode is 'broker'",
            setting="ASYNC_ASSESSMENT_BROKER_URL",
        )
    return RedisAsyncAssessmentBroker(
        url=broker_url,
        queue_name=settings.async_assessment.broker_queue_name,
        reservation_timeout_seconds=settings.async_assessment.broker_reservation_timeout_seconds,
    )
