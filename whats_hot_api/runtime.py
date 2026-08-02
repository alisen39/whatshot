"""Explicit Core runtime dependencies attached to each FastAPI app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.config import Settings
from whats_hot_api.fetch import FetchService


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    settings: Settings
    routes: RouteCatalog
    cache: Any
    fetch: FetchService
