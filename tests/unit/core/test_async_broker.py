from __future__ import annotations

import sys
import types

import pytest

from scalescore.core.async_broker import RedisAsyncAssessmentBroker


class FakeRedisClient:
    def __init__(self) -> None:
        self.commands: list[tuple[object, ...]] = []
        self.ready: list[str] = []
        self.processing: list[str] = []
        self.values: dict[str, str] = {}
        self.deleted_keys: list[str] = []

    def rpush(self, name: str, value: str) -> None:
        self.commands.append(("rpush", name, value))
        self.ready.append(value)

    def execute_command(self, *args: object) -> str | None:
        self.commands.append(args)
        if args[:1] != ("BLMOVE",):
            raise AssertionError(f"unexpected command: {args}")
        if not self.ready:
            return None
        job_id = self.ready.pop(0)
        self.processing.append(job_id)
        return job_id

    def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.commands.append(("set", key, value, ex))
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.commands.append(("delete", key))
        self.values.pop(key, None)
        self.deleted_keys.append(key)

    def lrem(self, name: str, count: int, value: str) -> int:
        self.commands.append(("lrem", name, count, value))
        if name != "queue:processing" or value not in self.processing:
            return 0
        self.processing.remove(value)
        return 1

    def lrange(self, name: str, start: int, end: int) -> list[str]:
        self.commands.append(("lrange", name, start, end))
        assert name == "queue:processing"
        return list(self.processing)

    def get(self, key: str) -> str | None:
        self.commands.append(("get", key))
        return self.values.get(key)


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedisClient:
    client = FakeRedisClient()
    redis_module = types.ModuleType("redis")

    class Redis:
        @staticmethod
        def from_url(url: str, *, decode_responses: bool) -> FakeRedisClient:
            assert url == "redis://localhost:6379/0"
            assert decode_responses is True
            return client

    redis_module.Redis = Redis
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    return client


def test_redis_broker_reserves_with_processing_list(fake_redis: FakeRedisClient) -> None:
    broker = RedisAsyncAssessmentBroker(
        url="redis://localhost:6379/0",
        queue_name="queue",
        reservation_timeout_seconds=30,
    )
    broker.enqueue("job-1")

    job_id = broker.dequeue(timeout_seconds=5)

    assert job_id == "job-1"
    assert ("BLMOVE", "queue", "queue:processing", "LEFT", "RIGHT", 5) in fake_redis.commands
    assert fake_redis.ready == []
    assert fake_redis.processing == ["job-1"]
    assert fake_redis.values["queue:processing:reservation:job-1"] != ""


def test_redis_broker_acknowledges_reserved_job(fake_redis: FakeRedisClient) -> None:
    broker = RedisAsyncAssessmentBroker(
        url="redis://localhost:6379/0",
        queue_name="queue",
        reservation_timeout_seconds=30,
    )
    fake_redis.processing.append("job-1")
    fake_redis.values["queue:processing:reservation:job-1"] = "100.0"

    broker.acknowledge("job-1")

    assert fake_redis.processing == []
    assert "queue:processing:reservation:job-1" in fake_redis.deleted_keys


def test_redis_broker_requeues_stale_reservation_without_timestamp(
    fake_redis: FakeRedisClient,
) -> None:
    broker = RedisAsyncAssessmentBroker(
        url="redis://localhost:6379/0",
        queue_name="queue",
        reservation_timeout_seconds=30,
    )
    fake_redis.processing.append("job-1")

    recovered = broker.recover_stale_reservations()

    assert recovered == 1
    assert fake_redis.processing == []
    assert fake_redis.ready == ["job-1"]
