from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import openrouter, openrouter_announcements
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/openrouter/{board_type}",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def test_openrouter_exposes_curated_board_space():
    assert list(openrouter.TYPE_MAP) == [
        "models-week",
        "models-day",
        "models-month",
        "models-trending",
        "performance-throughput",
        "performance-latency",
        "benchmark-intelligence",
        "benchmark-coding",
        "benchmark-agentic",
        "apps-day",
        "apps-week",
        "apps-month",
    ]
    assert openrouter.ROUTE_META["params"]["type"]["type"] is openrouter.TYPE_MAP
    assert openrouter_announcements.ROUTE_META["params"]["type"]["type"] == {
        "announcements": "官方公告"
    }


@pytest.mark.asyncio
async def test_openrouter_model_board_maps_catalog_and_usage(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/rankings/models")
        assert kwargs["params"] == {"view": "week"}
        return RequestResult(
            False,
            "openrouter-models-update",
            {
                "data": [
                    {
                        "date": "2026-07-21 00:00:00",
                        "model_permaslug": "vendor/model-20260720",
                        "variant": "standard",
                        "variant_permaslug": "vendor/model-20260720",
                        "total_prompt_tokens": 120,
                        "total_completion_tokens": 30,
                        "count": 12,
                        "change": 4.25,
                        "total_tool_calls": 3,
                    }
                ]
            },
        )

    async def fake_catalog():
        return {
            "vendor/model-20260720": {
                "permaslug": "vendor/model-20260720",
                "slug": "vendor/model",
                "name": "Vendor: Model",
                "author": "vendor",
            }
        }

    monkeypatch.setattr(openrouter, "get", fake_get)
    monkeypatch.setattr(openrouter, "_load_catalog", fake_catalog)

    result = await openrouter.handle_route(_request("models-week"), no_cache=True)
    item = result.data[0]

    assert result.type == "LLM 榜 · 本周"
    assert result.updateTime == "openrouter-models-update"
    assert item.id == "vendor/model-20260720"
    assert item.title == "Vendor: Model"
    assert item.hot == 150
    assert item.timestamp == 1784563200000
    assert item.url == "https://openrouter.ai/vendor/model"
    assert "较上期 +4.2%" in (item.desc or "")


@pytest.mark.asyncio
async def test_openrouter_latency_board_tolerates_missing_request_count(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/rankings/performance")
        return RequestResult(
            False,
            "openrouter-performance-update",
            {
                "data": [
                    {
                        "id": "vendor/slower",
                        "name": "Slower",
                        "author": "vendor",
                        "p50_latency": 900,
                        "p50_throughput": 70,
                        "best_latency_provider": "Provider B",
                    },
                    {
                        "id": "vendor/faster",
                        "name": "Faster",
                        "author": "vendor",
                        "p50_latency": 400,
                        "p50_throughput": 50,
                        "best_latency_provider": "Provider A",
                    },
                ]
            },
        )

    monkeypatch.setattr(openrouter, "get", fake_get)
    result = await openrouter.handle_route(
        _request("performance-latency"),
        no_cache=True,
    )

    assert [item.id for item in result.data] == ["vendor/faster", "vendor/slower"]
    assert result.data[0].hot is None
    assert "P50 延迟 400 ms" in (result.data[0].desc or "")


@pytest.mark.asyncio
async def test_openrouter_benchmark_board_sorts_scores(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/rankings/benchmarks")
        return RequestResult(
            False,
            "openrouter-benchmark-update",
            {
                "data": {
                    "aaData": {
                        "coding": [
                            {
                                "uid": "vendor/model-low",
                                "permaslug": "vendor/model-low",
                                "aa_name": "Model Low",
                                "score": 55.4,
                            },
                            {
                                "uid": "vendor/model-high",
                                "permaslug": "vendor/model-high",
                                "aa_name": "Model High",
                                "score": 61.8,
                            },
                        ]
                    }
                }
            },
        )

    monkeypatch.setattr(openrouter, "get", fake_get)
    result = await openrouter.handle_route(
        _request("benchmark-coding"),
        no_cache=True,
    )

    assert [item.id for item in result.data] == [
        "vendor/model-high",
        "vendor/model-low",
    ]
    assert result.data[0].hot == 62
    assert result.data[0].desc == "Artificial Analysis 得分：61.8"


@pytest.mark.asyncio
async def test_openrouter_app_board_uses_rank_and_origin_url(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/rankings/apps")
        return RequestResult(
            False,
            "openrouter-apps-update",
            {
                "data": {
                    "day": [
                        {
                            "app_id": 2,
                            "rank": 2,
                            "total_tokens": "100",
                            "total_requests": 4,
                            "app": {
                                "id": 2,
                                "title": "Second",
                                "origin_url": "https://second.example/",
                                "categories": ["chat"],
                            },
                        },
                        {
                            "app_id": 1,
                            "rank": 1,
                            "total_tokens": "200",
                            "total_requests": 8,
                            "app": {
                                "id": 1,
                                "title": "First",
                                "origin_url": "https://first.example/",
                                "categories": ["agent", "cli"],
                            },
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(openrouter, "get", fake_get)
    result = await openrouter.handle_route(_request("apps-day"), no_cache=True)

    assert [item.id for item in result.data] == ["1", "2"]
    assert result.data[0].url == "https://first.example/"
    assert result.data[0].hot == 200
    assert "agent, cli" in (result.data[0].desc or "")
