from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any

import orjson

from whats_hot_api.config import config
from whats_hot_api.utils.logger import logger

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # type: ignore[assignment]


class CacheData:
    __slots__ = ("update_time", "data")

    def __init__(self, update_time: str, data: Any):
        self.update_time = update_time
        self.data = data


@dataclass(slots=True)
class _MemoryEntry:
    value: CacheData
    expires_at: float


class DualCache:
    _max_memory_size = 100

    def __init__(self) -> None:
        self._memory: OrderedDict[str, _MemoryEntry] = OrderedDict()
        self._redis: aioredis.Redis | None = None  # type: ignore[name-defined]
        self._redis_available = False
        self._redis_tried = False

    def _resolve_ttl(self, ttl: int | None) -> int:
        return config.CACHE_TTL if ttl is None else ttl

    def _purge_expired_memory(self) -> None:
        now = monotonic()
        expired_keys = [
            key for key, entry in self._memory.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            self._memory.pop(key, None)

    def _get_memory(self, key: str) -> CacheData | None:
        entry = self._memory.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            self._memory.pop(key, None)
            return None
        self._memory.move_to_end(key)
        return entry.value

    def _set_memory(self, key: str, value: CacheData, ttl: int) -> None:
        if ttl <= 0:
            self._memory.pop(key, None)
            return
        self._purge_expired_memory()
        self._memory[key] = _MemoryEntry(
            value=value,
            expires_at=monotonic() + ttl,
        )
        self._memory.move_to_end(key)
        while len(self._memory) > self._max_memory_size:
            self._memory.popitem(last=False)

    async def _ensure_redis(self) -> None:
        if self._redis_tried:
            return
        self._redis_tried = True
        if aioredis is None:
            return
        if not config.REDIS_HOST:
            return
        try:
            self._redis = aioredis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD or None,
                db=config.REDIS_DB,
                decode_responses=False,
            )
            await asyncio.wait_for(self._redis.ping(), timeout=2)
            self._redis_available = True
            logger.info("📦 [Redis] connected successfully.")
        except Exception as e:
            self._redis_available = False
            logger.error(f"📦 [Redis] connection failed: {e}")

    async def get(self, key: str) -> CacheData | None:
        await self._ensure_redis()
        if self._redis_available and self._redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    obj = orjson.loads(raw)
                    return CacheData(update_time=obj["updateTime"], data=obj["data"])
            except Exception as e:
                logger.error(f"📦 [Redis] get error: {e}")
        return self._get_memory(key)

    async def set(self, key: str, value: CacheData, ttl: int | None = None) -> None:
        ttl_seconds = self._resolve_ttl(ttl)
        await self._ensure_redis()
        if self._redis_available and self._redis:
            try:
                raw = orjson.dumps({"updateTime": value.update_time, "data": value.data})
                if ttl_seconds > 0:
                    await self._redis.set(key, raw, ex=ttl_seconds)
                else:
                    await self._redis.delete(key)
                logger.info(f"💾 [REDIS] {key} has been cached")
            except Exception as e:
                logger.error(f"📦 [Redis] set error: {e}")
        self._set_memory(key, value, ttl_seconds)
        logger.info(f"💾 [NodeCache] {key} has been cached")

    async def delete(self, key: str) -> None:
        await self._ensure_redis()
        if self._redis_available and self._redis:
            try:
                await self._redis.delete(key)
                logger.info(f"🗑️ [REDIS] {key} has been deleted from Redis")
            except Exception as e:
                logger.error(f"📦 [Redis] del error: {e}")
        self._memory.pop(key, None)
        logger.info(f"🗑️ [CACHE] {key} has been deleted from NodeCache")

    async def close(self) -> None:
        redis_client = self._redis
        self._redis = None
        self._redis_available = False
        self._redis_tried = False
        if redis_client:
            try:
                await redis_client.aclose()
            except RuntimeError as exc:
                if "Event loop is closed" not in str(exc):
                    raise
                logger.warning("⚠️ Redis client was bound to a closed event loop; discarded")
            except Exception as exc:
                logger.warning(f"⚠️ Redis close failed: {exc}")
        self._memory.clear()


cache = DualCache()
