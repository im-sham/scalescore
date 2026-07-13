from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from math import ceil
from threading import Lock
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from scalescore.config import RateLimitSettings


_REDIS_SLIDING_WINDOW_SCRIPT = """
local current_time = redis.call("TIME")
local now_ms = (current_time[1] * 1000) + math.floor(current_time[2] / 1000)
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local member = ARGV[3]

redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now_ms - window_ms)
local count = redis.call("ZCARD", KEYS[1])

if count >= limit then
    local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
    local retry_after = math.max(1, math.ceil((tonumber(oldest[2]) + window_ms - now_ms) / 1000))
    return {0, retry_after}
end

redis.call("ZADD", KEYS[1], now_ms, member)
redis.call("PEXPIRE", KEYS[1], window_ms)
return {1, 0}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiterUnavailable(RuntimeError):
    """Raised when the configured shared limiter cannot make a decision."""

    def __init__(self) -> None:
        super().__init__("Rate limiting service unavailable")


@runtime_checkable
class RateLimiter(Protocol):
    """Provider-neutral asynchronous request-limiter contract."""

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult: ...

    async def close(self) -> None: ...


def hash_rate_limit_key(logical_key: str, *, namespace: str) -> str:
    """Return a namespaced opaque digest for backend storage."""
    digest = sha256(logical_key.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


@dataclass
class _LocalWindow:
    events: deque[float]
    window_seconds: int


class LocalRateLimiter:
    """Bounded, process-local limiter for development and tests."""

    def __init__(
        self,
        *,
        max_keys: int,
        namespace: str = "local",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        self._max_keys = max_keys
        self._namespace = namespace
        self._clock = clock
        self._events: OrderedDict[str, _LocalWindow] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _discard_expired(bucket: _LocalWindow, *, now: float) -> None:
        window_start = now - bucket.window_seconds
        while bucket.events and bucket.events[0] <= window_start:
            bucket.events.popleft()

    def _make_room(self, *, now: float) -> None:
        for storage_key, bucket in list(self._events.items()):
            self._discard_expired(bucket, now=now)
            if not bucket.events:
                del self._events[storage_key]

        if len(self._events) >= self._max_keys:
            self._events.popitem(last=False)

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitResult(allowed=True)

        now = self._clock()
        storage_key = hash_rate_limit_key(key, namespace=self._namespace)

        with self._lock:
            bucket = self._events.get(storage_key)
            if bucket is not None:
                bucket.window_seconds = window_seconds
                self._discard_expired(bucket, now=now)
                if not bucket.events:
                    del self._events[storage_key]
                    bucket = None

            if bucket is None:
                self._make_room(now=now)
                bucket = _LocalWindow(events=deque(), window_seconds=window_seconds)
                self._events[storage_key] = bucket

            self._events.move_to_end(storage_key)
            if len(bucket.events) >= limit:
                retry_after = max(1, ceil(bucket.events[0] + window_seconds - now))
                return RateLimitResult(
                    allowed=False,
                    retry_after_seconds=retry_after,
                )

            bucket.events.append(now)
            return RateLimitResult(allowed=True)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    async def close(self) -> None:
        return None


class RedisRateLimiter:
    """Atomic Redis-backed sliding-window limiter."""

    def __init__(
        self,
        *,
        url: str,
        namespace: str,
        connect_timeout_seconds: float = 1.0,
        socket_timeout_seconds: float = 1.0,
    ) -> None:
        self._namespace = namespace
        self._client = Redis.from_url(
            url,
            socket_connect_timeout=connect_timeout_seconds,
            socket_timeout=socket_timeout_seconds,
            decode_responses=False,
        )

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitResult(allowed=True)

        storage_key = hash_rate_limit_key(key, namespace=self._namespace)
        try:
            response = await self._client.eval(
                _REDIS_SLIDING_WINDOW_SCRIPT,
                1,
                storage_key,
                limit,
                window_seconds * 1000,
                uuid4().hex,
            )
            allowed, retry_after = response
            return RateLimitResult(
                allowed=bool(allowed),
                retry_after_seconds=int(retry_after),
            )
        except (RedisError, TypeError, ValueError):
            raise RateLimiterUnavailable from None

    async def close(self) -> None:
        await self._client.aclose()


def build_rate_limiter(config: RateLimitSettings) -> RateLimiter:
    if config.backend == "local":
        return LocalRateLimiter(
            max_keys=config.local_max_keys,
            namespace=config.namespace,
        )

    if config.url is None:
        raise ValueError("RATE_LIMIT_URL is required when RATE_LIMIT_BACKEND=redis")
    return RedisRateLimiter(
        url=config.url.get_secret_value(),
        namespace=config.namespace,
        connect_timeout_seconds=config.connect_timeout_seconds,
        socket_timeout_seconds=config.socket_timeout_seconds,
    )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    from scalescore.config import settings

    return build_rate_limiter(settings.rate_limit)
