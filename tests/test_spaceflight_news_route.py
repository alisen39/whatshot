from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import spaceflight_news
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/spaceflight-news",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_spaceflight_news_maps_article_metadata(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"limit": "15"}
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "results": [
                    {
                        "id": 39004,
                        "title": "NASA Rover Reads Ancient Mars Impacts",
                        "authors": [{"name": "NASA"}],
                        "url": "https://www.nasa.gov/example",
                        "image_url": "https://www.nasa.gov/example.jpg",
                        "news_site": "NASA",
                        "summary": "<p>Ancient Martian rocks preserve an impact record.</p>",
                        "published_at": "2026-07-15T15:30:04Z",
                        "updated_at": "2026-07-15T15:30:16Z",
                        "featured": True,
                        "launches": [{"launch_id": "abc", "provider": "NASA"}],
                        "events": [],
                    }
                ]
            },
        )

    monkeypatch.setattr(spaceflight_news, "get", fake_get)
    route_data = await spaceflight_news.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "航天新闻"
    assert item.id == "39004"
    assert item.content == "Ancient Martian rocks preserve an impact record."
    assert item.contentStatus == "summary"
    assert item.source == "NASA"
    assert item.isImportant is True
    assert item.tags == ["NASA"]
    assert item.images == ["https://www.nasa.gov/example.jpg"]
    assert item.symbols == [{"launch_id": "abc", "provider": "NASA"}]
    assert item.timestamp == 1784129404000
