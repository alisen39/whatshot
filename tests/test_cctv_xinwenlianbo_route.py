from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import cctv_xinwenlianbo
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/cctv-xinwenlianbo",
            "query_string": query,
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_parses_daily_rundown(monkeypatch):
    html = """
    <ul>
      <li><a title="《新闻联播》 20260716 19:00" href="https://tv.cctv.com/full.shtml"><i class="sql0">完整版</i>完整版</a></li>
      <li>
        <div class="image"><a href="https://tv.cctv.com/2026/07/16/VIDEabc260716.shtml"><img src="//img.cctv.cn/a.jpg"></a><span>00:03:12</span></div>
        <a title="[视频]上半年GDP同比增长" href="https://tv.cctv.com/2026/07/16/VIDEabc260716.shtml"><i class="sql1">完整版</i>节目</a>
      </li>
    </ul>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/day/20260716.shtml")
        return RequestResult(False, "2026-07-16T12:00:00+00:00", html)

    monkeypatch.setattr(cctv_xinwenlianbo, "get", fake_get)
    route_data = await cctv_xinwenlianbo.handle_route(
        _request(b"day=20260716")
    )

    assert route_data.type == "20260716 节目单"
    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "VIDEabc260716"
    assert item.title == "上半年GDP同比增长"
    assert item.images == ["https://img.cctv.cn/a.jpg"]
    assert item.metrics == {"duration": "00:03:12"}
    assert item.url.endswith("/VIDEabc260716.shtml")


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_falls_back_one_day_when_today_is_empty(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs["url"])
        html = "" if len(calls) == 1 else "<li><a title='[视频]昨日节目' href='/yesterday.shtml'>节目</a></li>"
        return RequestResult(False, "2026-07-16T12:00:00+00:00", html)

    monkeypatch.setattr(cctv_xinwenlianbo, "get", fake_get)
    monkeypatch.setattr(cctv_xinwenlianbo, "_today", lambda: "20260716")
    route_data = await cctv_xinwenlianbo.handle_route(_request())

    assert calls[0].endswith("/day/20260716.shtml")
    assert calls[1].endswith("/day/20260715.shtml")
    assert route_data.type == "20260715 节目单"
    assert route_data.total == 1


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_rejects_invalid_day(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/day/20260716.shtml")
        return RequestResult(False, "2026-07-16T12:00:00+00:00", "")

    monkeypatch.setattr(cctv_xinwenlianbo, "get", fake_get)
    monkeypatch.setattr(cctv_xinwenlianbo, "_today", lambda: "20260716")
    monkeypatch.setattr(cctv_xinwenlianbo, "_previous_day", lambda day: day)
    await cctv_xinwenlianbo.handle_route(_request(b"day=../../etc/passwd"))
