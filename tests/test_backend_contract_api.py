from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from whats_hot_api.daemon.app import create_daemon_app
from whats_hot_api.daemon.backend_v1 import (
    BackendContractError,
    create_backend_v1_router,
    error_envelope,
)
from whats_hot_api.fetch import (
    CachePolicy,
    FetchCacheMissError,
    FetchRequest,
    FetchResult,
    FetchSourceNotFoundError,
    FetchUpstreamError,
    SourceDescriptor,
)
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.scheduler.config import (
    AppConfig,
    DaemonSettings,
    McpSettings,
    SchedulerSettings,
    StorageSettings,
)

NOW = datetime(2026, 8, 13, 8, 30, tzinfo=UTC)
CONTRACT_SCHEMAS = (
    Path(__file__).parents[2]
    / "whats-hot-mcp"
    / "contracts"
    / "jsonschema"
    / "v1"
)


def _source(
    site: str,
    *,
    kind: str = "hotlist",
    params: dict | None = None,
    types: tuple[str, ...] = ("hot",),
) -> SourceDescriptor:
    return SourceDescriptor(
        name=site,
        title=f"{site.title()} Source",
        description=f"{site} description",
        link=f"https://example.com/{site}",
        category=kind,
        category_label=kind,
        params=params,
        types=types,
        default_type=types[0],
        validate_type=True,
        data_path=f"/{site}/{{type}}",
    )


class _ContractFetchService:
    def __init__(self) -> None:
        self.requests: list[FetchRequest] = []
        self.sources = {
            "alpha": _source("alpha"),
            "demo": _source(
                "demo",
                params={
                    "type": {
                        "name": "榜单",
                        "type": {"hot": "热门", "new": "最新"},
                    },
                    "range": {
                        "name": "周期",
                        "type": {"DAY": "今日", "WEEK": "本周"},
                    },
                },
                types=("hot", "new"),
            ),
            "history": _source(
                "history",
                params={"month": "月份", "day": "日期"},
            ),
            "news": _source("news", kind="newsflash"),
            "weather": _source(
                "weather",
                params={
                    "province": {
                        "name": "区域",
                        "value": "省份名称",
                    }
                },
            ),
            "z-gold": _source("z-gold", kind="gold"),
        }

    def list_sources(self) -> tuple[SourceDescriptor, ...]:
        # Deliberately non-sorted: Contract routing must provide stable ordering.
        return tuple(reversed(self.sources.values()))

    def describe_source(self, site: str) -> SourceDescriptor:
        try:
            return self.sources[site]
        except KeyError:
            raise FetchSourceNotFoundError(
                f"Unknown source {site!r}.",
                details={"site": site},
            ) from None

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        if request.site == "failure":
            raise RuntimeError("SECRET token=abc /Users/private/config.toml")
        if request.site == "cache-miss":
            raise FetchCacheMissError("No cache", details={"site": request.site})
        if request.site == "upstream":
            raise FetchUpstreamError("secret upstream response")
        self.describe_source(request.site)
        from_cache = request.cache_policy is CachePolicy.ONLY
        return FetchResult(
            request=request,
            observed_at=NOW,
            data=RouterData(
                name=request.site,
                title=f"{request.site.title()} Results",
                type="测试榜",
                total=1,
                fromCache=from_cache,
                updateTime=NOW.isoformat(),
                data=[
                    ListItem(
                        id="item-1",
                        title="测试条目",
                        url="https://example.com/item-1",
                        mobileUrl="https://m.example.com/item-1",
                        hot=123,
                        desc="条目描述",
                        cover="https://example.com/cover.png",
                        author="作者",
                        timestamp=NOW.timestamp() * 1000,
                    )
                ],
            ),
        )


def _config(tmp_path: Path, *, max_items: int = 200) -> AppConfig:
    return AppConfig(
        daemon=DaemonSettings(state_path=tmp_path / "state"),
        storage=StorageSettings(enabled=False, path=tmp_path / "data.duckdb"),
        scheduler=SchedulerSettings(
            enabled=False,
            max_fetch_concurrency=2,
            jitter_seconds=0,
        ),
        mcp=McpSettings(enabled=False, max_result_items=max_items),
    )


async def _client(
    tmp_path: Path,
    service: _ContractFetchService,
    *,
    max_items: int = 200,
):
    app = create_daemon_app(
        _config(tmp_path, max_items=max_items),
        fetch_service=service,  # type: ignore[arg-type]
    )
    return app, AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:6690",
    )


class _RecordingHistoryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def call(self, method: str, *args, **kwargs):  # noqa: ANN003, ANN202
        self.calls.append((method, args, kwargs))
        coverage = {
            "historyEnabled": True,
            "earliestAvailableAt": None,
            "latestAvailableAt": None,
            "configuredSites": [],
            "complete": False,
            "limitations": ["test-fixture"],
        }
        if method == "get_data_coverage":
            return coverage
        if method == "get_trend_series":
            return {
                "site": kwargs["site"],
                "boardKey": kwargs["board_key"],
                "itemId": kwargs["item_id"],
                "bucket": kwargs["bucket"],
                "series": [],
                "coverage": coverage,
            }
        return {
            "items": [],
            "nextCursor": None,
            "truncated": False,
            "asOf": NOW,
            "coverage": coverage,
        }


def _history_contract_client(
    tmp_path: Path,
    service: _ContractFetchService,
    history: _RecordingHistoryService,
) -> AsyncClient:
    app = FastAPI()
    app.include_router(
        create_backend_v1_router(
            _config(tmp_path),
            fetch_service=service,
            history_service=history,
        )
    )

    @app.exception_handler(BackendContractError)
    async def handle_contract_error(
        request: Request,
        exc: BackendContractError,
    ) -> JSONResponse:
        return JSONResponse(
            error_envelope(request, exc),
            status_code=exc.status_code,
        )

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:6690",
    )


async def test_core_capabilities_are_public_and_exclude_history(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        response = await client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.headers["x-whatshot-contract-version"] == "1"
    assert response.headers["x-whatshot-board-key-version"] == "1"
    assert response.json()["data"]["profiles"] == ["core-read"]
    assert response.json()["data"]["boardKeyVersion"] == 1
    assert response.json()["data"]["features"] == {
        "sources": True,
        "sourceSchema": True,
        "current": True,
        "liveFetch": True,
        "batchCurrent": True,
        "history": False,
        "historySearch": False,
        "trendSeries": False,
        "coverage": False,
        "navigation": False,
        "semanticSearch": False,
        "kinds": ["gold", "hotlist", "newsflash"],
    }
    assert response.json()["meta"]["contractVersion"] == "1"
    assert "authorization" not in response.json()["data"]


async def test_sources_are_stable_filterable_and_cursor_bound(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        first = await client.get("/api/v1/sources", params={"limit": 2})
        cursor = first.json()["data"]["nextCursor"]
        second = await client.get(
            "/api/v1/sources",
            params={"limit": 2, "cursor": cursor},
        )
        mismatched = await client.get(
            "/api/v1/sources",
            params={"kind": "hotlist", "cursor": cursor},
        )
        filtered = await client.get(
            "/api/v1/sources",
            params={"kind": "gold"},
        )

    assert [row["site"] for row in first.json()["data"]["sources"]] == [
        "alpha",
        "demo",
    ]
    assert [row["site"] for row in second.json()["data"]["sources"]] == [
        "history",
        "news",
    ]
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "INVALID_CURSOR"
    assert [row["site"] for row in filtered.json()["data"]["sources"]] == [
        "z-gold"
    ]


async def test_source_detail_enumerates_canonical_boards_and_unknown_error(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        response = await client.get("/api/v1/sources/demo")
        dynamic = await client.get("/api/v1/sources/history")
        missing = await client.get(
            "/api/v1/sources/missing",
            headers={"X-Request-ID": "source-missing"},
        )

    boards = response.json()["data"]["boards"]
    assert [row["boardKey"] for row in boards] == [
        "type=hot&range=DAY",
        "type=hot&range=WEEK",
        "type=new&range=DAY",
        "type=new&range=WEEK",
    ]
    assert boards[0]["isDefault"] is True
    assert boards[0]["params"] == {"range": "DAY"}
    assert response.json()["data"]["dimensions"] == [
        {
            "key": "type",
            "label": "榜单",
            "location": "path",
            "dynamic": False,
            "options": [
                {"value": "hot", "label": "热门"},
                {"value": "new", "label": "最新"},
            ],
        },
        {
            "key": "range",
            "label": "周期",
            "location": "query",
            "dynamic": False,
            "options": [
                {"value": "DAY", "label": "今日"},
                {"value": "WEEK", "label": "本周"},
            ],
        },
    ]
    assert dynamic.json()["data"]["boards"][0]["boardKey"] == "hot"
    assert [row["key"] for row in dynamic.json()["data"]["dimensions"]] == [
        "month",
        "day",
    ]
    assert all(row["dynamic"] for row in dynamic.json()["data"]["dimensions"])
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "UNKNOWN_SOURCE",
            "message": "Unknown source.",
            "retryable": False,
            "details": {"site": "missing"},
        },
        "meta": {
            "requestId": "source-missing",
            "contractVersion": "1",
            "generatedAt": missing.json()["meta"]["generatedAt"],
        },
    }


async def test_current_resolves_default_dynamic_and_freshness(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        default = await client.post(
            "/api/v1/current",
            json={"site": "demo", "freshness": "live", "limit": 1},
        )
        dynamic = await client.post(
            "/api/v1/current",
            json={
                "site": "weather",
                "boardKey": "province=%E5%8C%97%E4%BA%AC%E5%B8%82%20%E6%B5%B7%E6%B7%80",
                "freshness": "cache_only",
            },
        )

    assert default.status_code == 200
    assert default.json()["data"]["boardKey"] == "type=hot&range=DAY"
    assert default.json()["data"]["sourceMode"] == "live"
    assert default.json()["data"]["items"][0] == {
        "itemId": "item-1",
        "rank": 1,
        "title": "测试条目",
        "url": "https://example.com/item-1",
        "mobileUrl": "https://m.example.com/item-1",
        "hot": 123,
        "description": "条目描述",
        "publishedAt": NOW.isoformat(),
        "extra": {
            "cover": "https://example.com/cover.png",
            "author": "作者",
        },
    }
    assert dynamic.status_code == 200
    assert dynamic.json()["data"]["sourceMode"] == "memory_cache"
    assert service.requests[0].cache_policy is CachePolicy.REFRESH
    assert service.requests[0].params == {"range": "DAY"}
    assert service.requests[1].cache_policy is CachePolicy.ONLY
    assert service.requests[1].params == {"province": "北京市 海淀"}


async def test_current_rejects_unknown_board_extra_fields_and_backend_limit(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service, max_items=10)
    async with app.router.lifespan_context(app), client:
        unknown = await client.post(
            "/api/v1/current",
            json={"site": "demo", "boardKey": "type=hot", "limit": 1},
        )
        extra = await client.post(
            "/api/v1/current",
            json={"site": "demo", "params": {}},
        )
        too_large = await client.post(
            "/api/v1/current",
            json={"site": "demo", "limit": 11},
        )
        query_extra = await client.post(
            "/api/v1/current?debug=true",
            json={"site": "demo", "limit": 1},
        )

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "UNKNOWN_BOARD"
    assert extra.status_code == 400
    assert extra.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert too_large.status_code == 400
    assert too_large.json()["error"]["details"] == {"maxResultItems": 10}
    assert query_extra.status_code == 400
    assert query_extra.json()["error"]["details"] == {"parameters": ["debug"]}


async def test_batch_returns_partial_errors_without_failing_successes(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        response = await client.post(
            "/api/v1/current/batch",
            json={
                "targets": [
                    {"site": "alpha"},
                    {"site": "missing"},
                ],
                "limitPerBoard": 1,
            },
        )
        oversized = await client.post(
            "/api/v1/current/batch",
            json={"targets": [{"site": "alpha"}] * 13},
        )

    assert response.status_code == 200
    assert [row["site"] for row in response.json()["data"]["results"]] == [
        "alpha"
    ]
    assert response.json()["data"]["errors"] == [
        {
            "site": "missing",
            "boardKey": None,
            "code": "UNKNOWN_SOURCE",
            "message": "Unknown source.",
            "retryable": False,
        }
    ]
    assert response.json()["data"]["truncated"] is False
    assert oversized.status_code == 400
    assert oversized.json()["error"]["details"] == {"maxBatchTargets": 12}


async def test_current_redacts_unexpected_backend_errors(tmp_path: Path) -> None:
    service = _ContractFetchService()
    service.sources["failure"] = _source("failure")
    service.sources["upstream"] = _source("upstream")
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        unexpected = await client.post(
            "/api/v1/current",
            json={"site": "failure"},
        )
        upstream = await client.post(
            "/api/v1/current",
            json={"site": "upstream"},
        )

    assert unexpected.status_code == 500
    assert unexpected.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "The Backend could not complete the request.",
        "retryable": False,
        "details": None,
    }
    assert "SECRET" not in unexpected.text
    assert "/Users/private" not in unexpected.text
    assert upstream.status_code == 503
    assert upstream.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert upstream.json()["error"]["retryable"] is True


async def test_core_contract_returns_stable_unavailable_for_disabled_history(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        response = await client.get("/api/v1/history")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "CAPABILITY_UNAVAILABLE",
        "message": "History capability is unavailable.",
        "retryable": False,
        "details": None,
    }


async def test_history_board_identity_is_canonical_known_and_legacy_readable(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    history = _RecordingHistoryService()
    async with _history_contract_client(tmp_path, service, history) as client:
        legacy = await client.get(
            "/api/v1/history",
            params={"site": "alpha", "boardKey": "default"},
        )
        canonical = await client.get(
            "/api/v1/history/search",
            params={
                "keyword": "ai",
                "site": "demo",
                "boardKey": "type=hot&range=DAY",
            },
        )
        noncanonical = await client.get(
            "/api/v1/history",
            params={"site": "demo", "boardKey": "range=DAY&type=hot"},
        )
        unknown = await client.get(
            "/api/v1/history",
            params={"site": "demo", "boardKey": "type=missing&range=DAY"},
        )
        unknown_source = await client.get(
            "/api/v1/coverage",
            params={"site": "missing"},
        )

    assert legacy.status_code == 200
    assert history.calls[0][2]["board_key"] == "hot"
    assert canonical.status_code == 200
    assert history.calls[1][2]["board_key"] == "type=hot&range=DAY"
    for response in (noncanonical, unknown):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "UNKNOWN_BOARD"
    assert unknown_source.status_code == 404
    assert unknown_source.json()["error"]["code"] == "UNKNOWN_SOURCE"
    assert len(history.calls) == 2


async def test_newsflash_trend_returns_capability_unavailable_without_querying_storage(
    tmp_path: Path,
) -> None:
    service = _ContractFetchService()
    history = _RecordingHistoryService()
    async with _history_contract_client(tmp_path, service, history) as client:
        response = await client.get(
            "/api/v1/history/trends",
            params={"site": "news", "boardKey": "hot", "itemId": "flash-1"},
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "CAPABILITY_UNAVAILABLE",
        "message": "Trend series are unavailable for newsflash boards.",
        "retryable": False,
        "details": None,
    }
    assert history.calls == []


async def test_contract_responses_validate_against_pinned_workspace_schemas(
    tmp_path: Path,
) -> None:
    if not CONTRACT_SCHEMAS.is_dir():
        pytest.skip("Adjacent whats-hot-mcp Contract artifacts are unavailable")
    jsonschema = pytest.importorskip("jsonschema")
    service = _ContractFetchService()
    app, client = await _client(tmp_path, service)
    async with app.router.lifespan_context(app), client:
        responses = {
            "capabilities-response": await client.get("/api/v1/capabilities"),
            "source-list-response": await client.get("/api/v1/sources"),
            "source-detail-response": await client.get("/api/v1/sources/demo"),
            "current-response": await client.post(
                "/api/v1/current", json={"site": "alpha"}
            ),
            "batch-current-response": await client.post(
                "/api/v1/current/batch",
                json={"targets": [{"site": "alpha"}]},
            ),
            "error-response": await client.get("/api/v1/sources/missing"),
        }

    for name, response in responses.items():
        schema = json.loads((CONTRACT_SCHEMAS / f"{name}.schema.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(response.json())
