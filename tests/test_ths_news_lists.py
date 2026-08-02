from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import ths_10jqka
from whats_hot_api.utils.http_client import RequestResult


def _request(query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/ths-10jqka",
        "query_string": query_string,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_ths_parses_finance_news_channel(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://news.10jqka.com.cn/cjzx_list/"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            """<div class="list-con"><li>
              <span class="arc-title"><a data-seq="678207556" href="http://news.10jqka.com.cn/20260716/c678207556.shtml">上半年GDP同比增长4.7%</a><span>07月16日 00:20</span></span>
              <a class="arc-cont">中国经济展现强大韧性活力...</a>
            </li></div>""",
        )

    monkeypatch.setattr(ths_10jqka, "get", fake_get)
    route_data = await ths_10jqka.handle_route(_request(b"type=macro"))
    item = route_data.data[0]

    assert route_data.type == "宏观经济"
    assert item.id == "678207556"
    assert item.content == "中国经济展现强大韧性活力..."
    assert item.contentStatus == "truncated"
    assert item.tags == ["宏观经济"]
    assert item.url == "https://news.10jqka.com.cn/20260716/c678207556.shtml"
    assert item.timestamp is not None


@pytest.mark.asyncio
async def test_ths_unknown_type_preserves_quick_default(monkeypatch):
    async def fake_flash(no_cache):  # noqa: ANN001, ARG001
        return {"from_cache": False, "update_time": "2026-07-16T00:00:00+00:00", "data": []}

    monkeypatch.setattr(ths_10jqka, "_get_flash_list", fake_flash)
    route_data = await ths_10jqka.handle_route(_request(b"type=unknown"))
    assert route_data.type == "快讯"
