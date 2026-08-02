from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import packagist
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_packagist_preserves_official_weekly_popularity_order(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://packagist.org/explore/popular.json"
        assert kwargs["params"] == {"per_page": "100"}
        assert kwargs["cache_key"].endswith("?per_page=100")
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {
                "packages": [
                    {
                        "name": "vendor/currently-popular",
                        "description": "Popular this week.",
                        "url": "https://packagist.org/packages/vendor/currently-popular",
                        "downloads": 500,
                        "favers": 20,
                    },
                    {
                        "name": "vendor/lifetime-leader",
                        "description": "More lifetime downloads.",
                        "url": "https://packagist.org/packages/vendor/lifetime-leader",
                        "downloads": 5_000,
                        "favers": 30,
                    },
                ],
                "total": 2,
                "next": None,
            },
        )

    monkeypatch.setattr(packagist, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/packagist",
        "query_string": b"",
        "headers": [],
    })
    route_data = await packagist.handle_route(request)

    assert route_data.type == "本周热门"
    assert [item.id for item in route_data.data] == [
        "vendor/currently-popular",
        "vendor/lifetime-leader",
    ]
    assert route_data.data[0].hot == 500
    assert route_data.data[1].hot == 5_000
    assert "本周热度排名：1" in route_data.data[0].desc
    assert "累计下载：500" in route_data.data[0].desc
    assert "收藏：20" in route_data.data[0].desc
