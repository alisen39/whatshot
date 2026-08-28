from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import yystv
from whats_hot_api.utils.http_client import RequestResult

HOUSE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
)


@pytest.mark.asyncio
async def test_yystv_request_carries_browser_user_agent(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return RequestResult(
            False,
            "2026-08-28T00:00:00+00:00",
            {"data": [{"id": 12345, "title": "游研社文章", "author": "作者", "createtime": 1787800000, "cover": "https://img.example.com/a.jpg"}]},
        )

    monkeypatch.setattr(yystv, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/yystv", "query_string": b"", "headers": []})
    result = await yystv.handle_route(request, no_cache=True)

    assert captured["headers"]["User-Agent"] == HOUSE_UA
    assert result.name == "yystv"
    assert result.total == 1
    assert result.data[0].url == "https://www.yystv.cn/p/12345"
