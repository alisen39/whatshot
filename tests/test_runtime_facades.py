from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as distribution_version

from whats_hot_api._version import get_version
from whats_hot_api.catalog import RouteCatalog


@dataclass
class _RouteInfo:
    handle_route: object
    category: str = "hotlist"
    category_label: str = "热榜"


def test_runtime_surfaces_share_distribution_version():
    assert get_version() == distribution_version("whats-hot-api")


def test_route_catalog_instances_do_not_share_registry_state():
    async def route_a(request, no_cache: bool = False):
        return None

    async def route_b(request, no_cache: bool = False):
        return None

    first_routes = {"a": _RouteInfo(route_a)}
    second_routes = {"b": _RouteInfo(route_b)}
    first = RouteCatalog(first_routes)
    second = RouteCatalog(second_routes)

    assert first.names() == ("a",)
    assert second.names() == ("b",)
    assert first.get("b") is None
    assert second.get("a") is None

    first_routes["c"] = _RouteInfo(route_a)
    assert first.names() == ("a", "c")
    assert second.names() == ("b",)


def test_create_app_exposes_explicit_core_runtime():
    from whats_hot_api.app import create_app
    from whats_hot_api.runtime import CoreRuntime

    app = create_app()

    runtime = app.state.core_runtime
    assert isinstance(runtime, CoreRuntime)
    assert runtime.routes.get("weibo") is not None
    assert runtime.settings is not None
    assert runtime.cache is not None
    assert runtime.fetch.describe_source("weibo").default_type == "hot"
    assert not hasattr(runtime, "snapshots")
