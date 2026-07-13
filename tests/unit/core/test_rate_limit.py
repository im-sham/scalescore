from __future__ import annotations

import asyncio

import pytest

from scalescore.core.rate_limit import LocalRateLimiter, RateLimiter, hash_rate_limit_key


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_local_limiter_implements_async_provider_protocol() -> None:
    limiter = LocalRateLimiter(max_keys=10)

    assert isinstance(limiter, RateLimiter)
    assert (await limiter.allow("workflow", limit=1, window_seconds=60)).allowed is True


@pytest.mark.asyncio
async def test_local_limiter_is_atomic_under_concurrent_contention() -> None:
    limiter = LocalRateLimiter(max_keys=10)

    decisions = await asyncio.gather(
        *(limiter.allow("shared-workflow", limit=7, window_seconds=60) for _ in range(100))
    )

    assert sum(decision.allowed for decision in decisions) == 7
    assert {decision.retry_after_seconds for decision in decisions if not decision.allowed} == {60}


@pytest.mark.asyncio
async def test_local_limiter_hashes_logical_keys_before_storage() -> None:
    limiter = LocalRateLimiter(max_keys=10, namespace="tests:rate-limit")
    logical_key = "auth:login:person@example.com:192.0.2.10"

    await limiter.allow(logical_key, limit=2, window_seconds=60)

    stored_keys = tuple(limiter._events)
    assert stored_keys == (hash_rate_limit_key(logical_key, namespace="tests:rate-limit"),)
    assert logical_key not in "".join(stored_keys)
    assert "person@example.com" not in "".join(stored_keys)


@pytest.mark.asyncio
async def test_local_limiter_removes_expired_keys_and_stays_strictly_bounded() -> None:
    clock = ManualClock()
    limiter = LocalRateLimiter(max_keys=3, clock=clock)

    for index in range(3):
        await limiter.allow(f"expired-{index}", limit=1, window_seconds=1)
    assert len(limiter._events) == 3

    clock.advance(2)
    await limiter.allow("current", limit=1, window_seconds=60)

    assert len(limiter._events) == 1
    assert tuple(limiter._events) == (hash_rate_limit_key("current", namespace="local"),)

    for index in range(100):
        await limiter.allow(f"high-cardinality-{index}", limit=1, window_seconds=60)
        assert len(limiter._events) <= 3


@pytest.mark.asyncio
async def test_local_limiter_prunes_mixed_window_expiry_before_evicting_live_state() -> None:
    clock = ManualClock()
    limiter = LocalRateLimiter(max_keys=2, clock=clock)
    long_key = hash_rate_limit_key("long-lived", namespace="local")
    expired_key = hash_rate_limit_key("short-lived", namespace="local")

    await limiter.allow("long-lived", limit=1, window_seconds=100)
    await limiter.allow("short-lived", limit=1, window_seconds=1)
    clock.advance(2)
    await limiter.allow("new", limit=1, window_seconds=60)

    assert long_key in limiter._events
    assert expired_key not in limiter._events
    denied = await limiter.allow("long-lived", limit=1, window_seconds=100)
    assert denied.allowed is False
    assert denied.retry_after_seconds == 98


@pytest.mark.asyncio
async def test_local_limiter_does_not_store_disabled_limits() -> None:
    limiter = LocalRateLimiter(max_keys=2)

    decision = await limiter.allow("disabled", limit=0, window_seconds=60)

    assert decision.allowed is True
    assert limiter._events == {}
