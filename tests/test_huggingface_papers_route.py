from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import huggingface_papers as hf_papers
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_huggingface_weekly_sorts_by_upvotes(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://huggingface.co/api/papers"
        assert kwargs["params"] == {"period": "weekly"}
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            [
                {"id": "2607.1", "title": "Lower", "upvotes": 2, "authors": []},
                {
                    "id": "2607.2",
                    "title": "Higher",
                    "upvotes": 20,
                    "authors": [
                        {"name": "A"},
                        {"name": "B"},
                        {"name": "C"},
                        {"name": "D"},
                    ],
                    "summary": "Paper summary",
                    "thumbnailUrl": "https://example.com/paper.png",
                    "publishedAt": "2026-07-14T00:00:00Z",
                },
            ],
        )

    monkeypatch.setattr(hf_papers, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/huggingface-papers", "query_string": b"type=weekly", "headers": []}
    )
    route_data = await hf_papers.handle_route(request)

    assert route_data.type == "Weekly 热门"
    assert [item.id for item in route_data.data] == ["2607.2", "2607.1"]
    assert route_data.data[0].author == "A, B, C et al."
    assert route_data.data[0].hot == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", ["daily", "papers"])
async def test_huggingface_daily_and_papers_use_official_api(monkeypatch, board_type):
    observed: dict[str, object] = {}

    async def fake_get(**kwargs):
        observed.update(kwargs)
        return RequestResult(
            False,
            "2026-08-27T00:00:00+00:00",
            [{"id": "2608.1", "title": "Daily paper", "upvotes": 5, "authors": []}],
        )

    monkeypatch.setattr(hf_papers, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/huggingface-papers", "query_string": f"type={board_type}".encode(), "headers": []}
    )
    route_data = await hf_papers.handle_route(request)

    assert observed["url"] == "https://huggingface.co/api/papers"
    assert observed["params"] == {"period": "day"}
    assert route_data.type == "Daily Papers"
    assert [item.id for item in route_data.data] == ["2608.1"]


def test_huggingface_papers_declares_cloud_board_type():
    from types import SimpleNamespace

    from whats_hot_api.catalog import RouteCatalog
    from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError

    route = SimpleNamespace(
        handle_route=hf_papers.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=hf_papers.ROUTE_META,
        validate_type=True,
    )
    service = FetchService(RouteCatalog({hf_papers.ROUTE_NAME: route}))
    described = service.describe_source("huggingface-papers")
    assert "papers" in described.types
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        import asyncio

        asyncio.run(service.fetch(FetchRequest(site="huggingface-papers", path_type="hot")))
