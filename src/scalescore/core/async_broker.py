from __future__ import annotations

from functools import lru_cache

from scalescore.config import settings
from scalescore.core.async_assessment import AsyncAssessmentQueueBroker
from scalescore.core.exceptions import ConfigurationError


class AsyncAssessmentBrokerError(RuntimeError):
    """Raised when async broker operations fail."""


class RedisAsyncAssessmentBroker:
    """Redis list-backed broker for async assessment job IDs."""

    def __init__(self, *, url: str, queue_name: str) -> None:
        try:
            import redis
        except ModuleNotFoundError as err:  # pragma: no cover - dependency check
            raise ConfigurationError(
                message=(
                    "redis dependency is required when ASYNC_ASSESSMENT_MODE=broker. "
                    "Install with: pip install 'redis>=5.0'"
                ),
                setting="ASYNC_ASSESSMENT_MODE",
            ) from err

        self._queue_name = queue_name
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
            payload = self._client.blpop(self._queue_name, timeout=timeout_seconds)
        except Exception as err:  # noqa: BLE001
            raise AsyncAssessmentBrokerError(
                "Failed to dequeue async assessment job from Redis broker"
            ) from err

        if payload is None:
            return None
        _, job_id = payload
        return str(job_id)


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
    )
