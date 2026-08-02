from __future__ import annotations

import asyncio
import base64
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from whats_hot_api.config import config
from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.logger import logger


class RequestResult:
    __slots__ = ("from_cache", "update_time", "data")

    def __init__(self, from_cache: bool, update_time: str, data: Any):
        self.from_cache = from_cache
        self.update_time = update_time
        self.data = data


class CacheOnlyMiss(Exception):
    """Raised when cache-only mode cannot satisfy an upstream request."""


_cache_only_mode: ContextVar[bool] = ContextVar("cache_only_mode", default=False)


@contextmanager
def force_cache_only():
    token = _cache_only_mode.set(True)
    try:
        yield
    finally:
        _cache_only_mode.reset(token)


# Per-proxy client pool: key = proxy URL ("" for no proxy)
_clients: dict[str, httpx.AsyncClient] = {}
_clients_lock = asyncio.Lock()

_LOCAL_PROXY_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_PRODUCTION_ENV_NAMES = {"prod", "production"}
_suppressed_local_proxies: set[str] = set()


def _resolve_cache_ttl(ttl: int | None) -> int:
    return config.HOTLIST_CACHE_TTL if ttl is None else ttl


def _build_cache_key(
    url: str,
    params: dict[str, Any] | None,
    override: str | None = None,
) -> str:
    if override:
        return override
    if not params:
        return url
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{url}?{qs}"


def _is_production_environment() -> bool:
    candidates = (
        getattr(config, "ENVIRONMENT", ""),
        os.getenv("ENVIRONMENT", ""),
        os.getenv("APP_ENV", ""),
        os.getenv("ENV", ""),
        os.getenv("NODE_ENV", ""),
    )
    return any(str(value).strip().lower() in _PRODUCTION_ENV_NAMES for value in candidates)


def _is_local_proxy(proxy_url: str) -> bool:
    try:
        hostname = urlparse(proxy_url).hostname
    except ValueError:
        return False
    if not hostname:
        return False
    return hostname in _LOCAL_PROXY_HOSTS or hostname.startswith("127.")


def _load_proxy_map() -> dict[str, str]:
    if not config.ROUTE_PROXY:
        return {}
    try:
        parsed = json.loads(config.ROUTE_PROXY)
    except (json.JSONDecodeError, TypeError):
        logger.warning("⚠️ ROUTE_PROXY is not valid JSON, ignoring")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("⚠️ ROUTE_PROXY must be a JSON object, ignoring")
        return {}
    return {
        str(keyword): str(proxy_url)
        for keyword, proxy_url in parsed.items()
        if keyword and proxy_url
    }


def _get_proxy_for_url(url: str) -> str | None:
    for keyword, proxy_url in _load_proxy_map().items():
        if keyword in url:
            if _is_production_environment() and _is_local_proxy(proxy_url):
                if proxy_url not in _suppressed_local_proxies:
                    logger.warning(
                        f"⚠️ Ignoring local ROUTE_PROXY in production: {proxy_url}"
                    )
                    _suppressed_local_proxies.add(proxy_url)
                return None
            return proxy_url
    return None


async def _get_client(proxy: str | None = None) -> httpx.AsyncClient:
    key = proxy or ""
    if key in _clients:
        return _clients[key]
    async with _clients_lock:
        if key not in _clients:
            kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(config.REQUEST_TIMEOUT / 1000),
                "follow_redirects": True,
                "http2": True,
            }
            if proxy:
                kwargs["proxy"] = proxy
                logger.info(f"🔗 [PROXY] Creating client with proxy: {proxy}")
            _clients[key] = httpx.AsyncClient(**kwargs)
    return _clients[key]


async def close_client() -> None:
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                raise
            logger.warning("⚠️ HTTP client was bound to a closed event loop; discarded")
        except Exception as exc:
            logger.warning(f"⚠️ HTTP client close failed: {exc}")


async def get(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    no_cache: bool = False,
    ttl: int | None = None,
    origin_info: bool = False,
    response_type: str = "json",
    proxy: str | None = None,
    cache_key: str | None = None,
) -> RequestResult:
    logger.info(f"🌐 [GET] {url}")
    key = _build_cache_key(url, params, cache_key)
    try:
        if _cache_only_mode.get():
            cached = await cache.get(key)
            if cached:
                logger.info("💾 [CACHE] The request is cached")
                return RequestResult(
                    from_cache=True,
                    update_time=cached.update_time,
                    data=cached.data,
                )
            raise CacheOnlyMiss(key)

        if not no_cache:
            cached = await cache.get(key)
            if cached:
                logger.info("💾 [CACHE] The request is cached")
                return RequestResult(
                    from_cache=True,
                    update_time=cached.update_time,
                    data=cached.data,
                )

        resolved_proxy = proxy or _get_proxy_for_url(url)
        client = await _get_client(resolved_proxy)
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()

        if response_type == "json":
            data = response.json()
        elif response_type == "text":
            data = response.text
        else:
            data = response.content

        if origin_info:
            data = {"data": data, "status": response.status_code, "headers": dict(response.headers)}

        update_time = datetime.now(timezone.utc).isoformat()
        await cache.set(
            key,
            CacheData(update_time=update_time, data=data),
            _resolve_cache_ttl(ttl),
        )
        logger.info(f"✅ [{response.status_code}] request was successful")
        return RequestResult(from_cache=False, update_time=update_time, data=data)
    except Exception:
        logger.error("❌ [ERROR] request failed")
        raise


async def post(
    url: str,
    headers: dict[str, str] | None = None,
    body: Any = None,
    no_cache: bool = False,
    ttl: int | None = None,
    origin_info: bool = False,
    response_type: str = "json",
    proxy: str | None = None,
    cache_key: str | None = None,
) -> RequestResult:
    logger.info(f"🌐 [POST] {url}")
    key = _build_cache_key(url, body if isinstance(body, dict) else None, cache_key)
    try:
        if _cache_only_mode.get():
            cached = await cache.get(key)
            if cached:
                logger.info("💾 [CACHE] The request is cached")
                return RequestResult(
                    from_cache=True,
                    update_time=cached.update_time,
                    data=cached.data,
                )
            raise CacheOnlyMiss(key)

        if not no_cache:
            cached = await cache.get(key)
            if cached:
                logger.info("💾 [CACHE] The request is cached")
                return RequestResult(
                    from_cache=True,
                    update_time=cached.update_time,
                    data=cached.data,
                )

        resolved_proxy = proxy or _get_proxy_for_url(url)
        client = await _get_client(resolved_proxy)
        if isinstance(body, (dict, list)):
            response = await client.post(url, headers=headers, json=body)
        else:
            response = await client.post(url, headers=headers, content=body)
        response.raise_for_status()
        if response_type == "json":
            data = response.json()
        elif response_type == "text":
            data = response.text
        elif response_type == "base64":
            data = base64.b64encode(response.content).decode("ascii")
        else:
            data = response.content

        if origin_info:
            data = {"data": data, "status": response.status_code, "headers": dict(response.headers)}

        update_time = datetime.now(timezone.utc).isoformat()
        await cache.set(
            key,
            CacheData(update_time=update_time, data=data),
            _resolve_cache_ttl(ttl),
        )
        logger.info(f"✅ [{response.status_code}] request was successful")
        return RequestResult(from_cache=False, update_time=update_time, data=data)
    except Exception:
        logger.error("❌ [ERROR] request failed")
        raise
