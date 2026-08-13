"""Backends shared by embedded HTTP MCP and the stdio proxy."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol

from whats_hot_api.daemon.client import DaemonClient
from whats_hot_api.daemon.runtime import DaemonRuntime
from whats_hot_api.fetch import (
    CachePolicy,
    FetchRequest,
    canonical_board_key,
)


class McpBackend(Protocol):
    async def list_sources(self) -> dict[str, Any]: ...
    async def get_source_schema(self, site: str) -> dict[str, Any]: ...
    async def fetch_current(
        self,
        site: str,
        path_type: str,
        params: dict[str, str],
        limit: int,
    ) -> dict[str, Any]: ...
    async def query_history(self, **kwargs: Any) -> dict[str, Any]: ...
    async def search_history(self, keyword: str, **kwargs: Any) -> dict[str, Any]: ...
    async def get_trend_series(self, **kwargs: Any) -> dict[str, Any]: ...
    async def get_storage_stats(self) -> dict[str, Any]: ...


class RuntimeMcpBackend:
    def __init__(self, runtime: DaemonRuntime) -> None:
        self.runtime = runtime

    async def list_sources(self) -> dict[str, Any]:
        return {
            "sources": [
                source.as_dict() for source in self.runtime.fetch_service.list_sources()
            ]
        }

    async def get_source_schema(self, site: str) -> dict[str, Any]:
        return {"source": self.runtime.fetch_service.describe_source(site).as_dict()}

    async def fetch_current(
        self,
        site: str,
        path_type: str,
        params: dict[str, str],
        limit: int,
    ) -> dict[str, Any]:
        result = await self.runtime.fetch_service.fetch(
            FetchRequest(
                site=site,
                path_type=path_type,
                params=params,
                limit=limit,
                cache_policy=CachePolicy.PREFER,
            )
        )
        descriptor = self.runtime.fetch_service.describe_source(site)
        board_key = canonical_board_key(
            path_type=path_type,
            params=params,
            declared_dimensions=(descriptor.params or {}).keys(),
        )
        return {
            "site": site,
            "boardKey": board_key,
            "kind": result.data.kind,
            "title": result.data.title,
            "type": result.data.type,
            "updateTime": result.data.updateTime,
            "observedAt": result.observed_at,
            "fromCache": result.from_cache,
            "items": [
                {"rank": rank, **item.model_dump(exclude_none=True)}
                for rank, item in enumerate(result.data.data, start=1)
            ],
        }

    async def query_history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.runtime.history.call("query_history", **kwargs)

    async def search_history(
        self,
        keyword: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self.runtime.history.call(
            "search_history",
            keyword,
            **kwargs,
        )

    async def get_trend_series(self, **kwargs: Any) -> dict[str, Any]:
        return await self.runtime.history.call("get_trend_series", **kwargs)

    async def get_storage_stats(self) -> dict[str, Any]:
        return await self.runtime.history.call("get_storage_stats")


class DaemonMcpBackend:
    """stdio backend that never opens DuckDB and only calls Control API."""

    def __init__(self, client: DaemonClient) -> None:
        self.client = client

    async def list_sources(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            "/internal/v1/sources",
        )

    async def get_source_schema(self, site: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            f"/internal/v1/sources/{site}",
        )

    async def fetch_current(
        self,
        site: str,
        path_type: str,
        params: dict[str, str],
        limit: int,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.post,
            f"/internal/v1/current/{site}/{path_type}",
            json={"params": params, "limit": limit},
        )

    async def query_history(self, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            "/internal/v1/history",
            params=_http_params(kwargs),
        )

    async def search_history(
        self,
        keyword: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            "/internal/v1/history/search",
            params={"keyword": keyword, **_http_params(kwargs)},
        )

    async def get_trend_series(self, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            "/internal/v1/history/trends",
            params=_http_params(kwargs),
        )

    async def get_storage_stats(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.get,
            "/internal/v1/storage/stats",
        )


def _http_params(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in values.items()
        if value is not None
    }
