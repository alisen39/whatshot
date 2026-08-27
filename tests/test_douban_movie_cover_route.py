from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_movie
from whats_hot_api.utils.http_client import RequestResult


def _request(path: str = "/douban-movie/hot") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"type=hot",
        "headers": [],
    })


def test_cover_url_extracts_string_large_from_dict():
    row_pic = {"large": "https://img1.doubanio.com/view/photo/m_ratio_poster/public/p2932993239.jpg"}
    assert douban_movie._cover_url(row_pic) == row_pic["large"]
    assert douban_movie._cover_url("https://example.com/a.jpg") == "https://example.com/a.jpg"
    assert douban_movie._cover_url({"large": 123}) is None
    assert douban_movie._cover_url({}) is None
    assert douban_movie._cover_url(None) is None


@pytest.mark.asyncio
async def test_hot_board_accepts_dict_pic(monkeypatch):
    payload = {
        "items": [
            {
                "id": "2932993",
                "title": "Flow",
                "card_subtitle": "Animation / 2026",
                "pic": {"large": "https://img1.doubanio.com/view/photo/m_ratio_poster/public/p2932993239.jpg"},
            },
            {"id": "1", "title": "No pic row"},
        ]
    }

    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-28T00:00:00+00:00", payload)

    monkeypatch.setattr(douban_movie, "get", fake_get)
    result = await douban_movie.handle_route(_request(), no_cache=True)

    assert result.total == 2
    assert result.data[0].cover == "https://img1.doubanio.com/view/photo/m_ratio_poster/public/p2932993239.jpg"
    assert result.data[1].cover is None
