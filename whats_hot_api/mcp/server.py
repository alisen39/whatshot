"""MCP v2 server with structured, read-only tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Literal

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from whats_hot_api._version import get_version
from whats_hot_api.daemon.client import DaemonClientError
from whats_hot_api.fetch import FetchError
from whats_hot_api.history.errors import HistoryError
from whats_hot_api.mcp.backend import McpBackend
from whats_hot_api.utils.logger import logger


class _McpInputError(ValueError):
    pass


def _tool_boundary[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await function(*args, **kwargs)
        except _McpInputError as exc:
            raise ValueError(str(exc)) from None
        except (FetchError, HistoryError, DaemonClientError) as exc:
            code = getattr(exc, "code", "REQUEST_FAILED")
            raise RuntimeError(f"{code}: WhatsHot request failed.") from None
        except Exception as exc:  # noqa: BLE001 - MCP is a public error boundary
            logger.error(
                f"MCP tool {function.__name__} failed with {type(exc).__name__}"
            )
            raise RuntimeError(
                "INTERNAL_ERROR: WhatsHot tool request failed."
            ) from None

    return guarded


class _Result(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class SourceListResult(_Result):
    sources: list[dict[str, Any]]


class SourceSchemaResult(_Result):
    source: dict[str, Any]


class CurrentFetchResult(_Result):
    site: str
    board_key: str = Field(alias="boardKey")
    kind: str
    title: str
    type: str
    update_time: str = Field(alias="updateTime")
    observed_at: datetime = Field(alias="observedAt")
    from_cache: bool = Field(alias="fromCache")
    items: list[dict[str, Any]]


class HistoryPageResult(_Result):
    items: list[dict[str, Any]]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    truncated: bool


class TrendResult(_Result):
    site: str
    board_key: str = Field(alias="boardKey")
    item_id: str = Field(alias="itemId")
    bucket: str
    series: list[dict[str, Any]]


class StorageStatsResult(_Result):
    enabled: bool = True
    captures: int | None = None
    hotlist_rows: int | None = Field(default=None, alias="hotlistRows")
    newsflash_items: int | None = Field(default=None, alias="newsflashItems")
    gold_rows: int | None = Field(default=None, alias="goldRows")
    latest_observed_at: datetime | None = Field(
        default=None,
        alias="latestObservedAt",
    )


_LOCAL_READ = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_OPEN_READ = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def build_mcp_server(
    backend: McpBackend,
    *,
    max_result_items: int = 200,
    default_history_days: int = 7,
    max_history_days: int = 365,
) -> MCPServer:
    if not 1 <= max_result_items <= 200:
        raise ValueError("max_result_items must be between 1 and 200")
    default_result_limit = min(50, max_result_items)
    server = MCPServer(
        "whatshot",
        title="WhatsHot",
        description="Current and historical trending-list evidence.",
        version=get_version(),
        instructions=(
            "Use current fetch only when live data is required. Prefer history "
            "tools for evidence over time. Every history item includes source, "
            "board, observation time, capture id, and URL."
        ),
    )

    @server.tool(
        description="List all discoverable WhatsHot sources without network access.",
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def list_sources() -> SourceListResult:
        return SourceListResult.model_validate(await backend.list_sources())

    @server.tool(
        description="Describe one source, its boards, and accepted parameters.",
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def get_source_schema(site: str) -> SourceSchemaResult:
        return SourceSchemaResult.model_validate(await backend.get_source_schema(site))

    @server.tool(
        description=(
            "Fetch a current board. This may access the upstream website but "
            "never persists a history capture."
        ),
        annotations=_OPEN_READ,
    )
    @_tool_boundary
    async def fetch_current(
        site: str,
        path_type: str = "hot",
        params: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> CurrentFetchResult:
        effective_limit = default_result_limit if limit is None else limit
        if not 1 <= effective_limit <= max_result_items:
            raise _McpInputError(f"limit must be between 1 and {max_result_items}")
        return CurrentFetchResult.model_validate(
            await backend.fetch_current(
                site,
                path_type,
                params or {},
                effective_limit,
            )
        )

    @server.tool(
        description="Query persisted historical items with cursor pagination.",
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def query_history(
        site: str | None = None,
        board_key: str | None = None,
        kind: Literal["hotlist", "newsflash", "gold"] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> HistoryPageResult:
        effective_limit = default_result_limit if limit is None else limit
        if not 1 <= effective_limit <= max_result_items:
            raise _McpInputError(f"limit must be between 1 and {max_result_items}")
        since, until = _history_window(
            since,
            until,
            default_history_days=default_history_days,
            max_history_days=max_history_days,
        )
        return HistoryPageResult.model_validate(
            await backend.query_history(
                site=site,
                board_key=board_key,
                kind=kind,
                since=since,
                until=until,
                limit=effective_limit,
                cursor=cursor,
            )
        )

    @server.tool(
        description=(
            "Search persisted titles, descriptions, and newsflash content. "
            "Returns attributable evidence, not free-form summaries."
        ),
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def search_history(
        keyword: str,
        site: str | None = None,
        board_key: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> HistoryPageResult:
        effective_limit = default_result_limit if limit is None else limit
        if not 1 <= effective_limit <= max_result_items:
            raise _McpInputError(f"limit must be between 1 and {max_result_items}")
        since, until = _history_window(
            since,
            until,
            default_history_days=default_history_days,
            max_history_days=max_history_days,
        )
        return HistoryPageResult.model_validate(
            await backend.search_history(
                keyword,
                site=site,
                board_key=board_key,
                since=since,
                until=until,
                limit=effective_limit,
                cursor=cursor,
            )
        )

    @server.tool(
        description="Get rank and hot-value trends for one historical item.",
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def get_trend_series(
        site: str,
        board_key: str,
        item_id: str,
        bucket: Literal["10m", "1h", "6h", "1d"] = "1h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> TrendResult:
        since, until = _history_window(
            since,
            until,
            default_history_days=default_history_days,
            max_history_days=max_history_days,
        )
        return TrendResult.model_validate(
            await backend.get_trend_series(
                site=site,
                board_key=board_key,
                item_id=item_id,
                bucket=bucket,
                since=since,
                until=until,
            )
        )

    @server.tool(
        description="Return local history storage counts and freshness.",
        annotations=_LOCAL_READ,
    )
    @_tool_boundary
    async def get_storage_stats() -> StorageStatsResult:
        return StorageStatsResult.model_validate(await backend.get_storage_stats())

    return server


def _history_window(
    since: datetime | None,
    until: datetime | None,
    *,
    default_history_days: int,
    max_history_days: int,
) -> tuple[datetime, datetime]:
    end = until or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    start = since or end - timedelta(days=default_history_days)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if start > end:
        raise _McpInputError("since must not be after until")
    if end - start > timedelta(days=max_history_days):
        raise _McpInputError(f"history range must not exceed {max_history_days} days")
    return start, end
