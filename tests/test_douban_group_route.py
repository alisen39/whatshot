from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_group
from whats_hot_api.utils.http_client import RequestResult

HOUSE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
)
SAMPLE_HTML = (
    '<div class="article"><div class="channel-item">'
    '<h3><a href="https://www.douban.com/group/topic/123456/">周末徒步</a></h3>'
    '<div class="pic-wrap"><img src="https://img.doubanio.com/a.jpg"/></div>'
    '<div class="block"><p>活动描述</p></div><span class="pubtime">08-28</span>'
    '</div></div>'
)


@pytest.mark.asyncio
async def test_douban_group_request_carries_browser_user_agent(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-28T00:00:00+00:00", SAMPLE_HTML)

    monkeypatch.setattr(douban_group, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/douban-group", "query_string": b"", "headers": []})
    result = await douban_group.handle_route(request, no_cache=True)

    assert captured["headers"]["User-Agent"] == HOUSE_UA
    assert result.name == "douban-group"
    assert result.total == 1
    assert result.data[0].title == "周末徒步"
    assert result.data[0].url == "https://www.douban.com/group/topic/123456/"
