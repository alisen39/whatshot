from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import steam
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_steam_top_sellers_deduplicates_and_builds_store_urls(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "top_sellers": {
                    "items": [
                        {"id": 10, "type": 0, "name": "Game", "final_price": 7560, "discount_percent": 30, "header_image": "https://example.com/game.jpg"},
                        {"id": 10, "type": 0, "name": "Game", "final_price": 7560, "discount_percent": 30},
                        {"id": 20, "type": 1, "name": "Package", "final_price": 10300, "discount_percent": 0},
                    ]
                }
            },
        )

    monkeypatch.setattr(steam, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/steam",
            "query_string": b"type=top-sellers",
            "headers": [],
        }
    )
    route_data = await steam.handle_route(request)

    assert route_data.type == "热销商品榜"
    assert route_data.total == 2
    assert route_data.data[0].id == "app:10"
    assert route_data.data[0].desc == "售价：¥75.60 · 优惠：30%"
    assert route_data.data[0].url == "https://store.steampowered.com/app/10/"
    assert route_data.data[1].id == "sub:20"
    assert route_data.data[1].url == "https://store.steampowered.com/sub/20/"
