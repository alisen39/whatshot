from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from whats_hot_api.utils import cache as cache_mod
from whats_hot_api.utils.cache import CacheData, DualCache
from whats_hot_api.utils.logger import logger


class _FakeRedis:
    def __init__(self) -> None:
        self.ping_results: list[object] = []
        self.pings = 0
        self.store: dict[str, bytes] = {}

    async def ping(self) -> bool:
        self.pings += 1
        result = self.ping_results.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, asyncio.Event):
            await result.wait()
        return True

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def redis_env(monkeypatch):
    now = [100.0]
    client = _FakeRedis()
    created: list[dict] = []

    def make_client(**kwargs):
        created.append(kwargs)
        return client

    monkeypatch.setattr(cache_mod, "monotonic", lambda: now[0])
    monkeypatch.setattr(cache_mod.config, "REDIS_HOST", "redis.test")
    monkeypatch.setattr(cache_mod, "aioredis", SimpleNamespace(Redis=make_client))
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    yield SimpleNamespace(now=now, client=client, created=created, messages=messages)
    logger.remove(handler_id)


def _count(messages: list[str], text: str) -> int:
    return sum(text in message for message in messages)


async def test_failed_connect_uses_memory_and_waits_before_retrying(redis_env):
    redis_env.client.ping_results = [ConnectionError("refused")]
    cache = DualCache()

    await cache.set("k", CacheData(update_time="t", data={"v": 1}), 600)
    redis_env.now[0] += 29
    cached = await cache.get("k")
    await cache.delete("other")

    assert cached is not None and cached.data == {"v": 1}
    assert redis_env.client.store == {}
    assert redis_env.client.pings == 1
    assert _count(redis_env.messages, "📦 [Redis] connection failed: refused") == 1


async def test_retry_after_interval_connects_and_stops_pinging(redis_env):
    redis_env.client.ping_results = [TimeoutError(), True]
    cache = DualCache()

    await cache.get("k")
    redis_env.now[0] += 30
    await cache.set("k", CacheData(update_time="t", data={"v": 1}), 600)
    redis_env.now[0] += 3600
    cached = await cache.get("k")
    await cache.delete("k")

    assert cached is not None and cached.data == {"v": 1}
    assert redis_env.client.pings == 2
    assert len(redis_env.created) == 1
    assert redis_env.client.store == {}
    assert _count(redis_env.messages, "connection failed") == 1
    assert _count(redis_env.messages, "📦 [Redis] connected successfully.") == 1
    assert _count(redis_env.messages, "💾 [REDIS] k has been cached") == 1


async def test_requests_during_a_retry_do_not_wait_for_the_ping(redis_env):
    release = asyncio.Event()
    redis_env.client.ping_results = [ConnectionError("refused"), release]
    cache = DualCache()
    await cache.set("k", CacheData(update_time="t", data={"v": 1}), 600)
    redis_env.now[0] += 30

    retry = asyncio.create_task(cache.get("other"))
    await asyncio.sleep(0)
    cached = await cache.get("k")

    assert cached is not None and cached.data == {"v": 1}
    assert redis_env.client.pings == 2
    assert not retry.done()
    release.set()
    await retry
