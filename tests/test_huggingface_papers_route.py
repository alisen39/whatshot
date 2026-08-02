from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import huggingface_papers as hf_papers
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_huggingface_weekly_sorts_by_upvotes(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
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
async def test_huggingface_daily_uses_owned_rsshub_board(monkeypatch):
    async def fake_fetch_rsshub_feed(**kwargs):  # noqa: ANN003
        assert kwargs == {"route_name": "huggingface-papers", "route_path": "/huggingface/daily-papers", "params": {}, "no_cache": False}
        return {
            "from_cache": True,
            "update_time": "2026-07-16T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(hf_papers, "fetch_rsshub_feed", fake_fetch_rsshub_feed)
    request = Request(
        {"type": "http", "method": "GET", "path": "/huggingface-papers", "query_string": b"type=daily", "headers": []}
    )
    route_data = await hf_papers.handle_route(request)
    assert route_data.type == "Daily Papers"
    assert route_data.fromCache is True
