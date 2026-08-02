from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import devto
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_url", "expected_params"),
    [
        ("top", "https://dev.to/api/articles", {"top": "1", "per_page": "50"}),
        (
            "latest",
            "https://dev.to/api/articles/latest",
            {"per_page": "50", "page": "1"},
        ),
    ],
)
async def test_devto_api_boards(monkeypatch, board_type, expected_url, expected_params):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == expected_url
        assert kwargs["params"] == expected_params
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            [
                {
                    "id": 4151246,
                    "title": "The AI Jackpot",
                    "description": "Why prompting feels like gambling.",
                    "url": "https://dev.to/example/the-ai-jackpot",
                    "user": {"username": "example"},
                    "tag_list": ["ai", "discuss"],
                    "public_reactions_count": 42,
                    "comments_count": 7,
                    "reading_time_minutes": 5,
                    "published_at": "2026-07-16T00:00:00Z",
                    "cover_image": "https://example.com/cover.png",
                }
            ],
        )

    monkeypatch.setattr(devto, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/devto",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )
    route_data = await devto.handle_route(request)

    assert route_data.type == devto.type_map[board_type]
    assert route_data.data[0].id == "4151246"
    assert route_data.data[0].author == "example"
    assert route_data.data[0].hot == 42
    assert "标签：ai、discuss" in route_data.data[0].desc


@pytest.mark.asyncio
async def test_devto_feed_uses_its_official_rss(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://dev.to/feed"
        return RequestResult(True, "2026-07-16T00:00:00+00:00", "<rss><channel /></rss>")

    monkeypatch.setattr(devto, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/devto", "query_string": b"type=feed", "headers": []}
    )
    route_data = await devto.handle_route(request)

    assert route_data.type == "精选 RSS"
    assert route_data.fromCache is True
