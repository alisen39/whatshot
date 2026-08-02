from __future__ import annotations

from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import huodongxing
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": urlencode({"type": "upcoming"}).encode(), "headers": []})


HTML = """
<div class="search-tab-content-item-mesh">
  <a class="item-title" href="/event/123?x=1"><span>公开活动 A</span></a>
  <img class="item-logo" src="https://cdn.huodongxing.com/a.jpg">
  <div class="item-dress"><p>07/22 周三 ~ 07/25 周六</p><span class="item-dress-pp">线上活动</span></div>
  <div class="item-bottom-left"><p class="user-name">主办方 A</p></div>
</div>
<div class="search-tab-content-item-mesh">
  <a class="item-title" href="/event/123"><span>重复活动</span></a>
</div>
<div class="search-tab-content-item-mesh">
  <a class="item-title" href="/event/456"><span>公开活动 B</span></a>
  <div class="item-dress"><p>08/01 周六</p><span class="item-dress-pp">北京</span></div>
</div>
"""


def test_parser_keeps_stable_event_identity_and_canonical_urls() -> None:
    rows = huodongxing._parse_events(HTML)
    assert [row.id for row in rows] == ["123", "456"]
    assert rows[0].url == "https://www.huodongxing.com/event/123"
    assert rows[0].author == "主办方 A"
    assert rows[0].cover.endswith("a.jpg")
    assert rows[0].timestamp is not None
    assert huodongxing._parse_start_timestamp("今天 09:30") is not None
    assert huodongxing._parse_start_timestamp("明天 08:30") is not None


@pytest.mark.asyncio
async def test_route_uses_public_events_page(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.huodongxing.com/events"
        return RequestResult(False, "update", HTML)

    monkeypatch.setattr(huodongxing, "get", fake_get)
    result = await huodongxing.handle_route(_request())
    assert result.name == "huodongxing"
    assert result.type == "近期活动"
    assert result.total == 2
