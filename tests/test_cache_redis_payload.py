from __future__ import annotations

import orjson

from whats_hot_api.utils.cache import CacheData, DualCache


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _redis_backed_cache() -> tuple[DualCache, _FakeRedis]:
    cache = DualCache()
    redis = _FakeRedis()
    cache._redis = redis  # type: ignore[assignment]
    cache._redis_available = True
    cache._redis_tried = True
    return cache, redis


async def test_raw_response_bodies_round_trip_through_redis():
    # arraybuffer routes (e.g. GBK pages decoded by the route) cache bytes.
    body = "吾爱破解".encode("gbk") + b"\x00\xff"
    writer, redis = _redis_backed_cache()
    await writer.set("gbk-page", CacheData(update_time="2026-10-23T00:00:00+00:00", data=body), 60)

    assert "gbk-page" in redis.store
    reader = DualCache()  # another process: nothing in memory, only Redis
    reader._redis, reader._redis_available, reader._redis_tried = redis, True, True
    cached = await reader.get("gbk-page")

    assert cached is not None
    assert cached.data == body
    assert cached.update_time == "2026-10-23T00:00:00+00:00"


async def test_json_payloads_keep_their_redis_format():
    cache, redis = _redis_backed_cache()
    await cache.set("json", CacheData(update_time="t", data={"items": [1, "二"]}), 60)

    assert orjson.loads(redis.store["json"]) == {"updateTime": "t", "data": {"items": [1, "二"]}}
    cached = await cache.get("json")
    assert cached is not None and cached.data == {"items": [1, "二"]}
