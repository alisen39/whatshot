from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from whats_hot_api import registry
from whats_hot_api.models import RouterData
from whats_hot_api.registry import _register_route, router
from whats_hot_api.utils import cache as cache_mod
from whats_hot_api.utils import http_client
from whats_hot_api.utils.rsshub import fetch_rsshub_feed


def test_client_keys_are_isolated_by_origin_and_proxy():
    first = http_client._client_key("https://one.invalid/a", None)
    same_origin = http_client._client_key("https://one.invalid/b", None)
    other_origin = http_client._client_key("https://two.invalid/a", None)
    proxied = http_client._client_key(
        "https://one.invalid/a",
        "http://proxy.invalid:8080",
    )

    assert first == same_origin
    assert first != other_origin
    assert first != proxied


@pytest.mark.asyncio
async def test_clients_are_reused_only_within_one_origin():
    await http_client.close_client()
    try:
        first = await http_client._get_client("https://one.invalid/a")
        same_origin = await http_client._get_client("https://one.invalid/b")
        other_origin = await http_client._get_client("https://two.invalid/a")

        assert first is same_origin
        assert first is not other_origin
    finally:
        await http_client.close_client()


class _PoisonedClient:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.started = asyncio.Event()
        self.is_closed = False

    async def _request(self):
        self.started.set()
        if self.failure is not None:
            raise self.failure
        await asyncio.Event().wait()

    async def get(self, *args, **kwargs):
        return await self._request()

    async def post(self, *args, **kwargs):
        return await self._request()

    async def aclose(self) -> None:
        self.is_closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
async def test_cancelled_request_discards_only_its_origin_pool(method: str):
    url = f"https://cancelled-{method}.invalid/path"
    key = http_client._client_key(url, None)
    poisoned = _PoisonedClient()
    healthy_url = "https://healthy.invalid/path"
    healthy_key = http_client._client_key(healthy_url, None)
    healthy = _PoisonedClient()
    http_client._clients[key] = poisoned  # type: ignore[assignment]
    http_client._clients[healthy_key] = healthy  # type: ignore[assignment]

    request = (
        http_client.get(url, no_cache=True)
        if method == "get"
        else http_client.post(url, body={"ok": True}, no_cache=True)
    )
    task = asyncio.create_task(request)
    await poisoned.started.wait()
    task.cancel()

    try:
        with pytest.raises(asyncio.CancelledError):
            await task

        assert poisoned.is_closed is True
        assert key not in http_client._clients
        assert http_client._clients[healthy_key] is healthy
        assert healthy.is_closed is False
    finally:
        http_client._clients.pop(key, None)
        http_client._clients.pop(healthy_key, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
async def test_pool_timeout_discards_poisoned_origin_pool(method: str):
    url = f"https://pool-timeout-{method}.invalid/path"
    key = http_client._client_key(url, None)
    poisoned = _PoisonedClient(httpx.PoolTimeout("pool exhausted"))
    http_client._clients[key] = poisoned  # type: ignore[assignment]

    request = (
        http_client.get(url, no_cache=True)
        if method == "get"
        else http_client.post(url, body={"ok": True}, no_cache=True)
    )
    try:
        with pytest.raises(httpx.PoolTimeout):
            await request

        assert poisoned.is_closed is True
        assert key not in http_client._clients
    finally:
        http_client._clients.pop(key, None)


@pytest.mark.asyncio
async def test_cache_only_hit_returns_cached_data():
    key = f"https://cache-only-hit.invalid/{uuid4()}"
    await http_client.cache.set(
        key,
        http_client.CacheData(
            update_time="2026-06-21T00:00:00+00:00",
            data={"ok": True},
        ),
        ttl=60,
    )

    try:
        with http_client.force_cache_only():
            result = await http_client.get(key)

        assert result.from_cache is True
        assert result.data == {"ok": True}
    finally:
        await http_client.cache.delete(key)


@pytest.mark.asyncio
async def test_cache_only_miss_does_not_open_http_client(monkeypatch):
    key = f"https://cache-only-miss.invalid/{uuid4()}"
    opened_client = False

    async def fail_if_client_opens(proxy: str | None = None):  # noqa: ARG001
        nonlocal opened_client
        opened_client = True
        raise AssertionError("cache-only mode should not open an HTTP client")

    monkeypatch.setattr(http_client, "_get_client", fail_if_client_opens)

    with pytest.raises(http_client.CacheOnlyMiss):
        with http_client.force_cache_only():
            await http_client.get(key)

    assert opened_client is False


@pytest.mark.asyncio
async def test_route_cache_only_miss_returns_404_without_http_client(monkeypatch):
    route_name = f"cache-only-{uuid4().hex}"
    opened_client = False

    async def fail_if_client_opens(proxy: str | None = None):  # noqa: ARG001
        nonlocal opened_client
        opened_client = True
        raise AssertionError("cache-only mode should not open an HTTP client")

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        await http_client.get(f"https://route-cache-only-miss.invalid/{uuid4()}")
        return RouterData(
            name=route_name,
            title="Cache Only",
            type="test",
            total=0,
            fromCache=True,
            updateTime="2026-06-21T00:00:00+00:00",
            data=[],
        )

    monkeypatch.setattr(http_client, "_get_client", fail_if_client_opens)
    _register_route(route_name, handle_route)

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/{route_name}/hot?cache=only")

    assert resp.status_code == 404
    assert resp.json()["code"] == 404
    assert opened_client is False


@pytest.mark.asyncio
async def test_route_cache_only_returns_http_cache_hit(monkeypatch):
    route_name = f"cache-only-hit-{uuid4().hex}"
    cache_key = f"https://cache-only-route-hit.invalid/{uuid4()}"
    called_handler = False

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        nonlocal called_handler
        called_handler = True
        result = await http_client.get(cache_key)
        return RouterData(
            name=route_name,
            title=result.data["title"],
            type="test",
            total=1,
            fromCache=result.from_cache,
            updateTime=result.update_time,
            data=[
                {
                    "id": "1",
                    "title": result.data["title"],
                    "url": "https://example.com",
                    "mobileUrl": "https://example.com",
                    "hot": 1,
                }
            ],
        )

    await http_client.cache.set(
        cache_key,
        http_client.CacheData(
            update_time="2026-06-22T00:00:00+00:00",
            data={"title": "Fresher HTTP Cache"},
        ),
        ttl=60,
    )
    _register_route(route_name, handle_route)

    app = FastAPI()
    app.include_router(router)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(f"/{route_name}/hot?cache=only")
    finally:
        await http_client.cache.delete(cache_key)

    body = resp.json()
    assert resp.status_code == 200
    assert body["fromCache"] is True
    assert body["data"][0]["title"] == "Fresher HTTP Cache"
    assert called_handler is True


@pytest.mark.asyncio
async def test_default_variant_cache_only_miss_returns_404(monkeypatch):
    route_name = f"cache-only-default-miss-{uuid4().hex}"
    called_handler = False

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        nonlocal called_handler
        called_handler = True
        await http_client.get(f"https://cache-only-default-miss.invalid/{uuid4()}")
        raise AssertionError("unreachable")

    _register_route(route_name, handle_route)
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/{route_name}/hot?cache=only")

    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert called_handler is True


@pytest.mark.asyncio
async def test_non_default_variant_cache_only_miss_returns_404(monkeypatch):
    route_name = f"cache-only-variant-{uuid4().hex}"

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        assert request.query_params["type"] == "weekly"
        await http_client.get(f"https://cache-only-variant-miss.invalid/{uuid4()}")
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        registry,
        "_get_route_meta",
        lambda handler: {  # noqa: ARG005
            "params": {
                "type": {
                    "name": "榜单",
                    "type": {"daily": "日榜", "weekly": "周榜"},
                }
            }
        },
    )
    _register_route(route_name, handle_route)
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/{route_name}/weekly?cache=only")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_native_rsshub_cache_miss_returns_404_without_network(
    monkeypatch,
):
    route_name = f"cache-only-source-{uuid4().hex}"
    opened_client = False
    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        list_data = await fetch_rsshub_feed(
            route_name=route_name,
            route_path="/example/test",
            params={},
            no_cache=no_cache,
        )
        return RouterData(name=route_name, title="WhatsHot RSSHub source", type="hot", total=len(list_data["data"]), fromCache=list_data["from_cache"], updateTime=list_data["update_time"], data=list_data["data"])

    async def fail_if_client_opens(proxy: str | None = None):  # noqa: ARG001
        nonlocal opened_client
        opened_client = True
        raise AssertionError("cache-only source route must not open HTTP client")

    monkeypatch.setattr(http_client, "_get_client", fail_if_client_opens)
    _register_route(route_name, handle_route)
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/{route_name}/hot?cache=only")

    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert opened_client is False


@pytest.mark.asyncio
async def test_memory_cache_honors_per_entry_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache_mod, "monotonic", lambda: now[0])

    memory_cache = cache_mod.DualCache()
    memory_cache._redis_tried = True

    await memory_cache.set(
        "short",
        cache_mod.CacheData(
            update_time="2026-06-21T00:00:00+00:00",
            data={"value": "short"},
        ),
        ttl=1,
    )
    await memory_cache.set(
        "long",
        cache_mod.CacheData(
            update_time="2026-06-21T00:00:00+00:00",
            data={"value": "long"},
        ),
        ttl=60,
    )

    now[0] = 102.0

    assert await memory_cache.get("short") is None
    cached = await memory_cache.get("long")
    assert cached is not None
    assert cached.data == {"value": "long"}


def test_route_proxy_ignores_local_proxy_in_production(monkeypatch):
    for env_name in ("ENVIRONMENT", "APP_ENV", "ENV", "NODE_ENV"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(http_client.config, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        http_client.config,
        "ROUTE_PROXY",
        '{"github.com":"http://127.0.0.1:7890"}',
    )
    http_client._suppressed_local_proxies.clear()

    assert http_client._get_proxy_for_url("https://github.com/trending") is None


def test_route_proxy_allows_local_proxy_outside_production(monkeypatch):
    for env_name in ("ENVIRONMENT", "APP_ENV", "ENV", "NODE_ENV"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(http_client.config, "ENVIRONMENT", "")
    monkeypatch.setattr(
        http_client.config,
        "ROUTE_PROXY",
        '{"github.com":"http://127.0.0.1:7890"}',
    )

    assert (
        http_client._get_proxy_for_url("https://github.com/trending")
        == "http://127.0.0.1:7890"
    )


def test_build_cache_key_distinguishes_params():
    url = "https://example.invalid/api"

    assert http_client._build_cache_key(url, None) == url
    assert http_client._build_cache_key(url, {}) == url

    key_a = http_client._build_cache_key(url, {"channel": "a", "limit": "50"})
    key_b = http_client._build_cache_key(url, {"limit": "50", "channel": "b"})
    assert key_a != key_b
    assert key_a == http_client._build_cache_key(url, {"limit": "50", "channel": "a"})

    assert http_client._build_cache_key(url, {"channel": "a"}, override="stable") == "stable"


@pytest.mark.asyncio
async def test_get_caches_different_params_independently(monkeypatch):
    base = f"https://params-cache.invalid/{uuid4()}"
    seen_params: list[dict] = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    async def fake_get(self, url, headers=None, params=None):  # noqa: ARG001
        seen_params.append(dict(params or {}))
        return FakeResponse({"echo": dict(params or {})})

    monkeypatch.setattr(http_client.httpx.AsyncClient, "get", fake_get)

    first = await http_client.get(base, params={"channel": "a-stock"}, ttl=60)
    second = await http_client.get(base, params={"channel": "us-stock"}, ttl=60)
    cached_a = await http_client.get(base, params={"channel": "a-stock"}, ttl=60)

    assert first.data == {"echo": {"channel": "a-stock"}}
    assert second.data == {"echo": {"channel": "us-stock"}}
    assert cached_a.data == {"echo": {"channel": "a-stock"}}
    assert cached_a.from_cache is True

    assert len(seen_params) == 2

    await http_client.cache.delete(http_client._build_cache_key(base, {"channel": "a-stock"}))
    await http_client.cache.delete(http_client._build_cache_key(base, {"channel": "us-stock"}))


@pytest.mark.asyncio
async def test_get_cache_key_override_ignores_params(monkeypatch):
    base = f"https://override-cache.invalid/{uuid4()}"
    upstream_calls = 0

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    async def fake_get(self, url, headers=None, params=None):  # noqa: ARG001
        nonlocal upstream_calls
        upstream_calls += 1
        return FakeResponse({"call": upstream_calls})

    monkeypatch.setattr(http_client.httpx.AsyncClient, "get", fake_get)

    first = await http_client.get(
        base, params={"timestamp": 1}, cache_key=base, ttl=60,
    )
    second = await http_client.get(
        base, params={"timestamp": 2}, cache_key=base, ttl=60,
    )

    assert first.data == {"call": 1}
    assert second.data == {"call": 1}
    assert second.from_cache is True
    assert upstream_calls == 1

    await http_client.cache.delete(base)


@pytest.mark.asyncio
async def test_post_can_cache_binary_response_as_base64(monkeypatch):
    base = f"https://binary-post.invalid/{uuid4()}"
    upstream_calls = 0

    class FakeResponse:
        status_code = 200
        content = b"\x00\xffgrpc-web"

        def raise_for_status(self):
            return None

    async def fake_post(self, url, headers=None, content=None):  # noqa: ARG001
        nonlocal upstream_calls
        upstream_calls += 1
        return FakeResponse()

    monkeypatch.setattr(http_client.httpx.AsyncClient, "post", fake_post)

    first = await http_client.post(
        base,
        body=b"request",
        response_type="base64",
        cache_key=base,
        ttl=60,
    )
    second = await http_client.post(
        base,
        body=b"request",
        response_type="base64",
        cache_key=base,
        ttl=60,
    )

    assert first.data == "AP9ncnBjLXdlYg=="
    assert second.data == first.data
    assert second.from_cache is True
    assert upstream_calls == 1

    await http_client.cache.delete(base)


@pytest.mark.asyncio
async def test_get_no_cache_bypasses_read_and_refreshes_cache(monkeypatch):
    base = f"https://no-cache-refresh.invalid/{uuid4()}"
    upstream_calls = 0

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"value": "fresh"}

        def raise_for_status(self):
            return None

    async def fake_get(self, url, headers=None, params=None):  # noqa: ARG001
        nonlocal upstream_calls
        upstream_calls += 1
        return FakeResponse()

    await http_client.cache.set(
        base,
        http_client.CacheData(
            update_time="2026-06-21T00:00:00+00:00",
            data={"value": "stale"},
        ),
        ttl=60,
    )
    monkeypatch.setattr(http_client.httpx.AsyncClient, "get", fake_get)

    try:
        refreshed = await http_client.get(base, no_cache=True, ttl=60)
        cached = await http_client.get(base, ttl=60)
    finally:
        await http_client.cache.delete(base)

    assert refreshed.from_cache is False
    assert refreshed.data == {"value": "fresh"}
    assert cached.from_cache is True
    assert cached.data == {"value": "fresh"}
    assert upstream_calls == 1


@pytest.mark.asyncio
async def test_get_no_cache_failure_keeps_existing_cache(monkeypatch):
    base = f"https://no-cache-failure.invalid/{uuid4()}"

    async def fake_get(self, url, headers=None, params=None):  # noqa: ARG001
        raise RuntimeError("upstream down")

    await http_client.cache.set(
        base,
        http_client.CacheData(
            update_time="2026-06-21T00:00:00+00:00",
            data={"value": "stale"},
        ),
        ttl=60,
    )
    monkeypatch.setattr(http_client.httpx.AsyncClient, "get", fake_get)

    try:
        with pytest.raises(RuntimeError):
            await http_client.get(base, no_cache=True, ttl=60)
        cached = await http_client.get(base, ttl=60)
    finally:
        await http_client.cache.delete(base)

    assert cached.from_cache is True
    assert cached.data == {"value": "stale"}
