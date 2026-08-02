"""WhatsHot API — Core package for aggregating trending/hot lists."""

from whats_hot_api.catalog import RouteCatalog, RouteSpec, route_catalog
from whats_hot_api.config import Settings, replace_config
from whats_hot_api.fetch import (
    CachePolicy,
    FetchRequest,
    FetchResult,
    FetchService,
    SourceDescriptor,
)
from whats_hot_api.registry import (
    all_routes,
    discover_and_register_routes,
    route_handlers,
)
from whats_hot_api.runtime import CoreRuntime

__all__ = [
    "CachePolicy",
    "CoreRuntime",
    "FetchRequest",
    "FetchResult",
    "FetchService",
    "RouteCatalog",
    "RouteSpec",
    "Settings",
    "SourceDescriptor",
    "all_routes",
    "create_app",
    "discover_and_register_routes",
    "replace_config",
    "route_catalog",
    "route_handlers",
]


def create_app(**kwargs):
    """Lazy import to avoid triggering route discovery at package import time."""
    from whats_hot_api.app import create_app as _create_app

    return _create_app(**kwargs)
