from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import pixiv
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", pixiv.type_map)
async def test_pixiv_public_rankings(monkeypatch, board_type):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["mode"] == board_type
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "contents": [
                    {
                        "illust_id": 147135953,
                        "title": "作品标题",
                        "user_name": "画师",
                        "illust_page_count": "2",
                        "illust_bookmark_count": 321,
                        "url": "https://i.pximg.net/cover.jpg",
                        "date": "2026年07月13日 00:00",
                        "tags": ["原创", "插画"],
                    }
                ]
            },
        )

    monkeypatch.setattr(pixiv, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/pixiv",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )
    route_data = await pixiv.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == pixiv.type_map[board_type]
    assert item.id == "147135953"
    assert item.hot == 321
    assert item.timestamp == 1783872000000
    assert item.url == "https://www.pixiv.net/artworks/147135953"
    assert item.desc == "页数：2 · 标签：原创、插画"
