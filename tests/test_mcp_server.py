from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from whats_hot_api.mcp.backend import DaemonMcpBackend
from whats_hot_api.mcp.server import build_mcp_server


class _FakeBackend:
    def __init__(self) -> None:
        self.fetch_limit: int | None = None
        self.history_limit: int | None = None

    async def list_sources(self) -> dict[str, Any]:
        return {"sources": [{"name": "demo", "defaultType": "hot"}]}

    async def get_source_schema(self, site: str) -> dict[str, Any]:
        return {"source": {"name": site, "defaultType": "hot"}}

    async def fetch_current(
        self,
        site: str,
        path_type: str,
        params: dict[str, str],
        limit: int,
    ) -> dict[str, Any]:
        self.fetch_limit = limit
        return {
            "site": site,
            "boardKey": path_type,
            "kind": "hotlist",
            "title": "Demo",
            "type": "热门",
            "updateTime": "2026-07-31T00:00:00+00:00",
            "observedAt": datetime.now(UTC),
            "fromCache": False,
            "items": [{"rank": 1, "id": "one", "title": "测试"}],
        }

    async def query_history(self, **kwargs: Any) -> dict[str, Any]:
        self.history_limit = kwargs["limit"]
        return {"items": [], "nextCursor": None, "truncated": False}

    async def search_history(
        self,
        keyword: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "items": [{"title": keyword}],
            "nextCursor": None,
            "truncated": False,
        }

    async def get_trend_series(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "site": kwargs["site"],
            "boardKey": kwargs["board_key"],
            "itemId": kwargs["item_id"],
            "bucket": kwargs["bucket"],
            "series": [],
        }

    async def get_storage_stats(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "captures": 0,
            "hotlistRows": 0,
            "newsflashItems": 0,
            "goldRows": 0,
        }


async def test_mcp_exposes_only_read_tools() -> None:
    server = build_mcp_server(_FakeBackend())
    tools = await server.list_tools()
    names = {tool.name for tool in tools}

    assert names == {
        "list_sources",
        "get_source_schema",
        "fetch_current",
        "query_history",
        "search_history",
        "get_trend_series",
        "get_storage_stats",
    }
    assert "execute_sql" not in names
    assert "trigger_scheduler" not in names
    history_tool = next(tool for tool in tools if tool.name == "query_history")
    assert history_tool.annotations.read_only_hint is True
    assert history_tool.annotations.open_world_hint is False


async def test_mcp_returns_structured_output() -> None:
    server = build_mcp_server(_FakeBackend())
    result = await server.call_tool(
        "search_history",
        {"keyword": "人工智能"},
    )

    assert result.is_error is False
    assert result.structured_content["items"][0]["title"] == "人工智能"
    assert result.structured_content["truncated"] is False


async def test_mcp_storage_stats_supports_disabled_storage() -> None:
    class DisabledBackend(_FakeBackend):
        async def get_storage_stats(self) -> dict[str, Any]:
            return {"enabled": False}

    server = build_mcp_server(DisabledBackend())
    result = await server.call_tool("get_storage_stats", {})

    assert result.is_error is False
    assert result.structured_content["enabled"] is False


async def test_mcp_redacts_unexpected_backend_errors() -> None:
    class SecretBackend(_FakeBackend):
        async def fetch_current(
            self,
            site: str,
            path_type: str,
            params: dict[str, str],
            limit: int,
        ) -> dict[str, Any]:
            raise RuntimeError("SECRET /Users/alisen/private.toml token=abc")

    server = build_mcp_server(SecretBackend())
    with pytest.raises(ToolError) as exc_info:
        await server.call_tool(
            "fetch_current",
            {"site": "demo"},
        )
    rendered = str(exc_info.value)

    assert "INTERNAL_ERROR" in rendered
    assert "SECRET" not in rendered
    assert "/Users/alisen" not in rendered
    assert "token=abc" not in rendered


async def test_mcp_small_result_limit_has_usable_default() -> None:
    backend = _FakeBackend()
    server = build_mcp_server(backend, max_result_items=10)

    current = await server.call_tool("fetch_current", {"site": "demo"})
    history = await server.call_tool("query_history", {})

    assert current.is_error is False
    assert history.is_error is False
    assert backend.fetch_limit == 10
    assert backend.history_limit == 10


async def test_stdio_backend_only_calls_daemon_control_api() -> None:
    class FakeClient:
        def get(self, path, *, params=None):
            if path == "/internal/v1/sources":
                return {"sources": []}
            if path == "/internal/v1/history":
                return {
                    "items": [{"title": "历史"}],
                    "nextCursor": None,
                    "truncated": False,
                }
            raise AssertionError(path)

        def post(self, path, *, json=None):
            raise AssertionError(path)

    server = build_mcp_server(DaemonMcpBackend(FakeClient()))
    sources = await server.call_tool("list_sources", {})
    history = await server.call_tool("query_history", {})

    assert sources.is_error is False
    assert sources.structured_content == {"sources": []}
    assert history.structured_content["items"][0]["title"] == "历史"


async def test_stdio_backend_errors_are_redacted() -> None:
    class SecretClient:
        def get(self, path, *, params=None):
            from whats_hot_api.daemon.client import DaemonClientError

            raise DaemonClientError(
                "SECRET /Users/alisen/private.toml token=abc",
                code="DAEMON_INVALID_RESPONSE",
            )

    server = build_mcp_server(DaemonMcpBackend(SecretClient()))
    with pytest.raises(ToolError) as exc_info:
        await server.call_tool("list_sources", {})
    rendered = str(exc_info.value)

    assert "DAEMON_INVALID_RESPONSE" in rendered
    assert "SECRET" not in rendered
    assert "/Users/alisen" not in rendered
    assert "token=abc" not in rendered
