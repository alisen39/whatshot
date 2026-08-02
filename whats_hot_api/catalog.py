"""Public read-only facade over the discovered Core route registry."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RouteSpec:
    name: str
    handle_route: Callable[..., Any]
    category: str
    category_label: str
    metadata: Mapping[str, Any] | None = None
    validate_type: bool = True


class RouteCatalog:
    """Expose immutable route specs without leaking the mutable registry dict."""

    def __init__(self, routes: Mapping[str, Any] | None = None) -> None:
        self._routes: Mapping[str, Any] = routes or {}

    def bind(self, routes: Mapping[str, Any]) -> None:
        self._routes = routes

    def get(self, name: str) -> RouteSpec | None:
        info = self._routes.get(name)
        if info is None:
            return None
        module = sys.modules.get(getattr(info.handle_route, "__module__", ""))
        metadata = getattr(info, "metadata", None)
        if not isinstance(metadata, Mapping):
            metadata = getattr(module, "ROUTE_META", None) if module else None
        return RouteSpec(
            name=name,
            handle_route=info.handle_route,
            category=info.category,
            category_label=info.category_label,
            metadata=metadata if isinstance(metadata, Mapping) else None,
            validate_type=bool(
                getattr(
                    info,
                    "validate_type",
                    getattr(module, "ROUTE_VALIDATE_TYPE", True) if module else True,
                )
            ),
        )

    def names(self) -> tuple[str, ...]:
        return tuple(self._routes.keys())

    def specs(self) -> tuple[RouteSpec, ...]:
        return tuple(
            spec for name in self.names() if (spec := self.get(name)) is not None
        )

    def __contains__(self, name: object) -> bool:
        return name in self._routes


route_catalog = RouteCatalog()
