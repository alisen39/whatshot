from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import apple_podcasts
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_apple_podcasts_extracts_country_chart(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/cn/podcasts/top/100/podcasts.json")
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "feed": {
                    "results": [
                        {
                            "id": "1582119137",
                            "name": "岩中花述",
                            "artistName": "GIADA",
                            "artworkUrl100": "https://example.com/cover.png",
                            "genres": [{"genreId": "1301", "name": "艺术"}],
                            "url": "https://podcasts.apple.com/cn/podcast/id1582119137",
                        },
                        {"id": "", "name": "无效条目", "url": ""},
                    ]
                }
            },
        )

    monkeypatch.setattr(apple_podcasts, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/apple-podcasts",
            "query_string": b"type=cn",
            "headers": [],
        }
    )
    route_data = await apple_podcasts.handle_route(request)

    assert route_data.type == "中国区 Top 100"
    assert route_data.total == 1
    assert route_data.link == "https://podcasts.apple.com/cn/charts"
    item = route_data.data[0]
    assert item.id == "1582119137"
    assert item.title == "岩中花述"
    assert item.author == "GIADA"
    assert item.desc == "艺术"
    assert item.cover == "https://example.com/cover.png"


@pytest.mark.asyncio
async def test_apple_podcasts_falls_back_to_cn(monkeypatch):
    seen_urls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        seen_urls.append(kwargs["url"])
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {"feed": {"results": []}},
        )

    monkeypatch.setattr(apple_podcasts, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/apple-podcasts",
            "query_string": b"type=invalid",
            "headers": [],
        }
    )
    route_data = await apple_podcasts.handle_route(request)

    assert route_data.type == "中国区 Top 100"
    assert "/cn/podcasts/" in seen_urls[0]
