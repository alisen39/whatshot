"""Tests for the /{site} (metadata) + /{site}/{type} (data) route split.

Metadata is cheap (built from the module's ``ROUTE_META``); the data endpoint
injects the path ``{type}`` into the handler's query params; unknown types are
rejected with 400 before the handler runs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from whats_hot_api.app import create_app
from whats_hot_api.models import RouterData
from whats_hot_api.registry import _register_route, router

app = create_app()


@pytest.fixture(scope="module")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_metadata_no_param_route(client: AsyncClient):
    resp = await client.get("/weibo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["name"] == "weibo"
    assert body["title"] == "微博"
    assert body["types"] == ["hot"]
    assert body["defaultType"] == "hot"
    assert body["dataPath"] == "/weibo/{type}"
    # Metadata carries no data fields
    assert "data" not in body
    assert "total" not in body


@pytest.mark.asyncio
async def test_metadata_type_param_route(client: AsyncClient):
    resp = await client.get("/bilibili")
    assert resp.status_code == 200
    body = resp.json()
    assert body["types"][0] == "0"  # default option is the first type_map key
    assert "1" in body["types"]
    assert body["defaultType"] == "0"
    assert body["dataPath"] == "/bilibili/{type}"
    assert "type" in (body.get("params") or {})
    assert "data" not in body


@pytest.mark.asyncio
async def test_metadata_sspai_list_type(client: AsyncClient):
    """sspai's type options are a list; the default option is its first entry."""
    resp = await client.get("/sspai")
    assert resp.status_code == 200
    body = resp.json()
    assert "热门文章" in body["types"]
    assert body["defaultType"] == "热门文章"


@pytest.mark.asyncio
async def test_unknown_type_returns_400(client: AsyncClient):
    resp = await client.get("/bilibili/999")
    assert resp.status_code == 400
    assert resp.json()["code"] == 400

    # No-param routes only accept "hot"
    resp2 = await client.get("/weibo/not-a-type")
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_unknown_type_does_not_call_handler():
    """Type validation rejects before the route handler runs."""
    route_name = f"meta-validate-{uuid4().hex}"
    called = False

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        nonlocal called
        called = True
        return RouterData(
            name=route_name, title="x", type="t", total=0,
            fromCache=False, updateTime="now", data=[],
        )

    _register_route(route_name, handle_route)
    sub = FastAPI()
    sub.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=sub), base_url="http://test") as c:
        resp = await c.get(f"/{route_name}/bogus")
    assert resp.status_code == 400
    assert called is False


@pytest.mark.asyncio
async def test_metadata_does_not_call_handler():
    """GET /{site} returns metadata without invoking handle_route (cheap)."""
    route_name = f"meta-cheap-{uuid4().hex}"
    called = False

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        nonlocal called
        called = True
        return RouterData(
            name=route_name, title="x", type="t", total=0,
            fromCache=False, updateTime="now", data=[],
        )

    _register_route(route_name, handle_route)
    sub = FastAPI()
    sub.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=sub), base_url="http://test") as c:
        resp = await c.get(f"/{route_name}")
    assert resp.status_code == 200
    assert resp.json()["types"] == ["hot"]
    assert called is False


@pytest.mark.asyncio
async def test_data_endpoint_injects_path_type():
    """GET /{site}/{type} injects the path type into the handler's query params."""
    route_name = f"meta-data-{uuid4().hex}"
    seen_type = None

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        nonlocal seen_type
        seen_type = request.query_params.get("type")
        return RouterData(
            name=route_name, title="x", type="t", total=0,
            fromCache=False, updateTime="now", data=[],
        )

    _register_route(route_name, handle_route)
    sub = FastAPI()
    sub.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=sub), base_url="http://test") as c:
        resp = await c.get(f"/{route_name}/hot")
    assert resp.status_code == 200
    assert seen_type == "hot"


@pytest.mark.asyncio
async def test_data_endpoint_omits_metadata_fields():
    """Data response shape is verified without depending on a live upstream."""
    route_name = f"meta-shape-{uuid4().hex}"

    async def handle_route(request, no_cache: bool = False):  # noqa: ARG001
        return RouterData(
            name=route_name,
            title="x",
            type="t",
            params={"type": {"name": "榜单", "type": {"hot": "热门"}}},
            total=0,
            fromCache=False,
            updateTime="now",
            data=[],
        )

    _register_route(route_name, handle_route)
    sub = FastAPI()
    sub.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=sub), base_url="http://test"
    ) as client:
        resp = await client.get(f"/{route_name}/hot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert "params" not in body
    assert "types" not in body
    assert "defaultType" not in body
