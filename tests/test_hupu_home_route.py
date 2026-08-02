from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import hupu
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_hupu_home_extracts_visible_hot_threads(monkeypatch):
    html = """
    <div class="list-item">
      <div class="t-info">
        <a class="hot" href="/640884347.html"><span class="t-title">首页帖子</span></a>
        <span class="t-lights">1.2万亮</span><span class="t-replies">235回复</span>
      </div>
      <div class="t-label"><a href="/12">历史区</a></div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://bbs.hupu.com/"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(hupu, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/hupu", "query_string": b"type=home", "headers": []}
    )
    route_data = await hupu.handle_route(request)

    assert route_data.type == "首页热门"
    item = route_data.data[0]
    assert item.id == "640884347"
    assert item.hot == 12000
    assert item.desc == "历史区 · 12000 亮 · 235 回复"
    assert item.url == "https://bbs.hupu.com/640884347.html"


def test_hupu_count_parser():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<span class="n">1.5万回复</span>', "html.parser")
    assert hupu._count(soup.select_one(".n")) == 15000
