from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from scalescore.api.main import app
from scalescore.config import RateLimitSettings, ServerSettings, Settings
from scalescore.core.rate_limit import (
    RedisRateLimiter,
    build_rate_limiter,
    get_rate_limiter,
)

REDIS_URL = os.environ.get("TEST_REDIS_RATE_LIMIT_URL", "redis://127.0.0.1:6379/15")
TEST_RUN_NAMESPACE = f"tests:rate-limit:{uuid4().hex}"


async def _allow_once_in_process(
    url: str,
    namespace: str,
    logical_key: str,
    start_at: float,
) -> tuple[int, bool, int]:
    limiter = RedisRateLimiter(
        url=url,
        namespace=namespace,
        connect_timeout_seconds=1.0,
        socket_timeout_seconds=1.0,
    )
    try:
        await asyncio.sleep(max(0.0, start_at - time.time()))
        decision = await limiter.allow(logical_key, limit=1, window_seconds=5)
        return os.getpid(), decision.allowed, decision.retry_after_seconds
    finally:
        await limiter.close()


def _process_allow_once(
    url: str,
    namespace: str,
    logical_key: str,
    start_at: float,
) -> tuple[int, bool, int]:
    return asyncio.run(_allow_once_in_process(url, namespace, logical_key, start_at))


async def _clear_test_keys(client: Redis) -> None:
    keys = [key async for key in client.scan_iter(match=f"{TEST_RUN_NAMESPACE}:*")]
    if keys:
        await client.delete(*keys)


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    await _clear_test_keys(client)
    try:
        yield client
    finally:
        await _clear_test_keys(client)
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_limiter_is_global_across_independent_processes(
    redis_client: Redis,
) -> None:
    del redis_client
    namespace = f"{TEST_RUN_NAMESPACE}:processes"
    logical_key = "tenant-sensitive-global-key"
    start_at = time.time() + 1.0
    process_context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=process_context) as executor:
        futures = [
            executor.submit(
                _process_allow_once,
                REDIS_URL,
                namespace,
                logical_key,
                start_at,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=15) for future in futures]

    assert len({pid for pid, _, _ in results}) == 2
    assert sum(allowed for _, allowed, _ in results) == 1
    assert {retry_after for _, allowed, retry_after in results if not allowed} == {5}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_limiter_is_atomic_under_cross_client_contention(
    redis_client: Redis,
) -> None:
    del redis_client
    namespace = f"{TEST_RUN_NAMESPACE}:contention"
    first = RedisRateLimiter(url=REDIS_URL, namespace=namespace)
    second = RedisRateLimiter(url=REDIS_URL, namespace=namespace)
    try:
        decisions = await asyncio.gather(
            *(
                (first if index % 2 else second).allow(
                    "shared-contention-key",
                    limit=11,
                    window_seconds=10,
                )
                for index in range(100)
            )
        )
    finally:
        await first.close()
        await second.close()

    assert sum(decision.allowed for decision in decisions) == 11
    assert all(decision.retry_after_seconds > 0 for decision in decisions if not decision.allowed)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_limiter_hashes_keys_reports_stable_retry_and_expires_storage(
    redis_client: Redis,
) -> None:
    namespace = f"{TEST_RUN_NAMESPACE}:ttl"
    limiter = RedisRateLimiter(url=REDIS_URL, namespace=namespace)
    logical_key = "auth:login:private-person@example.com:token-sentinel"
    try:
        assert (await limiter.allow(logical_key, limit=1, window_seconds=2)).allowed is True
        denied = await limiter.allow(logical_key, limit=1, window_seconds=2)

        stored_keys = await redis_client.keys(f"{namespace}:*")
        assert len(stored_keys) == 1
        assert logical_key not in stored_keys[0]
        assert "private-person@example.com" not in stored_keys[0]
        assert "token-sentinel" not in stored_keys[0]
        assert denied.allowed is False
        assert denied.retry_after_seconds == 2
        assert 0 < await redis_client.pttl(stored_keys[0]) <= 2_000

        await asyncio.sleep(2.1)
        assert await redis_client.exists(stored_keys[0]) == 0
    finally:
        await limiter.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_worker_configuration_builds_shared_redis_limiter(
    redis_client: Redis,
) -> None:
    del redis_client
    namespace = f"{TEST_RUN_NAMESPACE}:workers"
    configured = Settings(
        server=ServerSettings(workers=4),
        rate_limit=RateLimitSettings(
            backend="redis",
            url=REDIS_URL,
            namespace=namespace,
        ),
    )
    first = build_rate_limiter(configured.rate_limit)
    second = build_rate_limiter(configured.rate_limit)
    assert isinstance(first, RedisRateLimiter)
    assert isinstance(second, RedisRateLimiter)
    try:
        assert (await first.allow("global-worker-key", limit=1, window_seconds=5)).allowed
        denied = await second.allow("global-worker-key", limit=1, window_seconds=5)
    finally:
        await first.close()
        await second.close()

    assert denied.allowed is False
    assert denied.retry_after_seconds == 5


@pytest.mark.integration
def test_redis_outage_fails_closed_with_stable_redacted_response() -> None:
    outage_limiter = RedisRateLimiter(
        url="redis://:credential-sentinel@127.0.0.1:1/0",
        namespace="tests:outage",
        connect_timeout_seconds=0.1,
        socket_timeout_seconds=0.1,
    )
    app.dependency_overrides[get_rate_limiter] = lambda: outage_limiter
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "private-person@example.com", "password": "not-a-real-secret"},
            )
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)
        asyncio.run(outage_limiter.close())

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "RATE_LIMITER_UNAVAILABLE",
            "message": "Rate limiting service unavailable",
        }
    }
    assert "credential-sentinel" not in response.text
    assert "private-person@example.com" not in response.text
    assert "127.0.0.1" not in response.text
