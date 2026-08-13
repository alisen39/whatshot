from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from uuid import uuid4

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import (
    CachePolicy,
    FetchCacheMissError,
    FetchInvalidRequestError,
    FetchRequest,
    FetchService,
    FetchTypeNotFoundError,
)
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import CacheOnlyMiss


@dataclass
class _RouteInfo:
    handle_route: object
    category: str = "hotlist"
    category_label: str = "热榜"


def _service_for(
    handler,
    *,
    metadata: dict | None = None,
    validate_type: bool = True,
) -> FetchService:
    module_name = f"_fetch_test_{uuid4().hex}"
    module = ModuleType(module_name)
    module.ROUTE_META = (
        metadata
        if metadata is not None
        else {
            "name": "demo",
            "title": "Demo",
            "params": {
                "type": {
                    "name": "榜单",
                    "type": {"hot": "热门", "new": "最新"},
                }
            },
        }
    )
    module.ROUTE_VALIDATE_TYPE = validate_type
    sys.modules[module_name] = module
    handler.__module__ = module_name
    return FetchService(RouteCatalog({"demo": _RouteInfo(handler)}))


def _router_data(*, from_cache: bool = False) -> RouterData:
    return RouterData(
        name="demo",
        title="Demo",
        type="热门",
        total=2,
        fromCache=from_cache,
        updateTime="2026-07-31T00:00:00+00:00",
        data=[
            ListItem(id="1", title="one", url="https://example.com/1"),
            ListItem(id="2", title="two", url="https://example.com/2"),
        ],
    )


async def test_fetch_service_merges_path_type_and_params() -> None:
    observed: dict[str, object] = {}

    async def handler(request, no_cache: bool = False):
        observed["type"] = request.query_params.get("type")
        observed["range"] = request.query_params.get("range")
        observed["no_cache"] = no_cache
        return _router_data()

    service = _service_for(
        handler,
        metadata={
            "name": "demo",
            "title": "Demo",
            "params": {
                "type": {
                    "name": "榜单",
                    "type": {"hot": "热门", "new": "最新"},
                },
                "range": {
                    "name": "周期",
                    "type": {"DAY": "日", "WEEK": "周"},
                },
            },
        },
    )
    result = await service.fetch(
        FetchRequest(
            site="demo",
            path_type="new",
            params={"range": "WEEK"},
            cache_policy=CachePolicy.REFRESH,
        )
    )

    assert observed == {"type": "new", "range": "WEEK", "no_cache": True}
    assert result.from_cache is False
    assert result.observed_at.tzinfo is not None
    assert result.data.updateTime == result.observed_at.isoformat()


async def test_fetch_service_rejects_duplicate_type_dimension_before_handler() -> None:
    called = False

    async def handler(request, no_cache: bool = False):
        nonlocal called
        called = True
        return _router_data()

    with pytest.raises(FetchInvalidRequestError, match="path_type"):
        await _service_for(handler).fetch(
            FetchRequest(
                site="demo",
                path_type="new",
                params={"type": "hot"},
            )
        )

    assert called is False


async def test_fetch_service_rejects_undeclared_dimension_before_handler() -> None:
    called = False

    async def handler(request, no_cache: bool = False):
        nonlocal called
        called = True
        return _router_data()

    with pytest.raises(FetchInvalidRequestError, match="not declared"):
        await _service_for(handler).fetch(
            FetchRequest(
                site="demo",
                path_type="new",
                params={"province": "北京市"},
            )
        )

    assert called is False


async def test_fetch_service_preserves_cached_response_time() -> None:
    async def handler(request, no_cache: bool = False):
        return _router_data(from_cache=True)

    result = await _service_for(handler).fetch(
        FetchRequest(site="demo", path_type="hot")
    )

    assert result.from_cache is True
    assert result.data.updateTime == "2026-07-31T00:00:00+00:00"


async def test_fetch_service_limits_a_copy_of_route_data() -> None:
    original = _router_data()

    async def handler(request, no_cache: bool = False):
        return original

    result = await _service_for(handler).fetch(
        FetchRequest(site="demo", path_type="hot", limit=1)
    )

    assert result.data.total == 1
    assert len(result.data.data) == 1
    assert original.total == 2
    assert len(original.data) == 2


async def test_fetch_service_rejects_unknown_type_before_handler() -> None:
    called = False

    async def handler(request, no_cache: bool = False):
        nonlocal called
        called = True
        return _router_data()

    with pytest.raises(FetchTypeNotFoundError) as exc_info:
        await _service_for(handler).fetch(
            FetchRequest(site="demo", path_type="missing")
        )

    assert called is False
    assert exc_info.value.details["validTypes"] == ["hot", "new"]


async def test_fetch_service_can_disable_type_validation() -> None:
    async def handler(request, no_cache: bool = False):
        return _router_data()

    result = await _service_for(handler, validate_type=False).fetch(
        FetchRequest(site="demo", path_type="arbitrary")
    )

    assert result.data.name == "demo"


async def test_fetch_service_maps_cache_only_miss() -> None:
    async def handler(request, no_cache: bool = False):
        raise CacheOnlyMiss("demo")

    with pytest.raises(FetchCacheMissError):
        await _service_for(handler).fetch(
            FetchRequest(
                site="demo",
                path_type="hot",
                cache_policy=CachePolicy.ONLY,
            )
        )


async def test_fetch_service_validates_limit() -> None:
    async def handler(request, no_cache: bool = False):
        return _router_data()

    with pytest.raises(FetchInvalidRequestError):
        await _service_for(handler).fetch(
            FetchRequest(site="demo", path_type="hot", limit=0)
        )


def test_source_descriptor_uses_hot_for_no_type_route() -> None:
    async def handler(request, no_cache: bool = False):
        return _router_data()

    source = _service_for(
        handler,
        metadata={"name": "demo", "title": "Demo"},
    ).describe_source("demo")

    assert source.types == ("hot",)
    assert source.default_type == "hot"
    assert source.data_path == "/demo/{type}"
