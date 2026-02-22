from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """In-memory sliding-window limiter for API abuse controls."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitResult(allowed=True)

        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= window_start:
                events.popleft()

            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now))
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

            events.append(now)
            return RateLimitResult(allowed=True)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


@lru_cache
def get_rate_limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter()
