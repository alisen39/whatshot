from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import aibase
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_aibase_extracts_ranked_daily_news(monkeypatch):
    html = """
    <div class="bg-white">
      <div class="grid">
        <a href="/news/29616">1 、 谷歌 Chrome 安卓版重构底部栏</a>
        <a href="https://www.aibase.com/news/29614">2，京东 AI Agent 与腾讯元宝合作</a>
        <a href="/news/29616">重复条目</a>
        <a href="/zh/daily">日报首页</a>
        <a href="/company/1">公司资料</a>
      </div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://www.aibase.com/zh/daily"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(aibase, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/aibase", "query_string": b"", "headers": []}
    )
    route_data = await aibase.handle_route(request)

    assert route_data.type == "每日 AI 趋势"
    assert route_data.total == 2
    assert [item.id for item in route_data.data] == ["29616", "29614"]
    assert [item.title for item in route_data.data] == [
        "谷歌 Chrome 安卓版重构底部栏",
        "京东 AI Agent 与腾讯元宝合作",
    ]
    assert route_data.data[1].url == "https://www.aibase.com/news/29614"
