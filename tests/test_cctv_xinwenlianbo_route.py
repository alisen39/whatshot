from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import cctv_xinwenlianbo
from whats_hot_api.utils.http_client import RequestResult

# 11-22 白天保存的上游响应：栏目首页最新一期是 20261121，今天（20261122）的日期页还是 404。
_FIXTURES = Path(__file__).parent / "fixtures"
_INDEX_URL = "https://tv.cctv.com/lm/xwlb/"
_DAY_20261121_URL = "https://tv.cctv.com/lm/xwlb/day/20261121.shtml"
_SAVED_PAGES = {
    _INDEX_URL: (_FIXTURES / "cctv-xinwenlianbo-index.html").read_text(encoding="utf-8"),
    _DAY_20261121_URL: (_FIXTURES / "cctv-xinwenlianbo-day-20261121.html").read_text(encoding="utf-8"),
}


def _saved_upstream(calls: list[str]):
    async def fake_get(**kwargs):  # noqa: ANN003
        url = kwargs["url"]
        calls.append(url)
        if url not in _SAVED_PAGES:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))
        return RequestResult(False, "2026-11-22T02:07:00+00:00", _SAVED_PAGES[url])

    return fake_get


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
async def test_cctv_xinwenlianbo_reads_latest_episode_day_from_index(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cctv_xinwenlianbo, "get", _saved_upstream(calls))
    monkeypatch.setattr(cctv_xinwenlianbo, "_today", lambda: "20261122")
    route_data = await cctv_xinwenlianbo.handle_route(_request())

    assert calls == [_INDEX_URL, _DAY_20261121_URL]
    assert route_data.type == "20261121 节目单"
    assert route_data.total == 12
    item = route_data.data[0]
    assert item.id == "VIDEKexfF0w6AqvGd2XN9sYh261121"
    assert item.metrics == {"duration": "00:05:51"}


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_explicit_day_skips_index(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cctv_xinwenlianbo, "get", _saved_upstream(calls))
    route_data = await cctv_xinwenlianbo.handle_route(_request(b"day=20261121"))

    assert calls == [_DAY_20261121_URL]
    assert route_data.type == "20261121 节目单"
    assert route_data.total == 12


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_without_index_episode_reads_today_then_previous_day(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs["url"])
        html = (
            "<li><a title='[视频]昨日节目' href='/yesterday.shtml'>节目</a></li>"
            if kwargs["url"].endswith("/day/20260715.shtml")
            else ""
        )
        return RequestResult(False, "2026-07-16T12:00:00+00:00", html)

    monkeypatch.setattr(cctv_xinwenlianbo, "get", fake_get)
    monkeypatch.setattr(cctv_xinwenlianbo, "_today", lambda: "20260716")
    route_data = await cctv_xinwenlianbo.handle_route(_request())

    assert calls == [
        _INDEX_URL,
        "https://tv.cctv.com/lm/xwlb/day/20260716.shtml",
        "https://tv.cctv.com/lm/xwlb/day/20260715.shtml",
    ]
    assert route_data.type == "20260715 节目单"
    assert route_data.total == 1


@pytest.mark.asyncio
async def test_cctv_xinwenlianbo_rejects_invalid_day(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] in {_INDEX_URL, "https://tv.cctv.com/lm/xwlb/day/20260716.shtml"}
        return RequestResult(False, "2026-07-16T12:00:00+00:00", "")

    monkeypatch.setattr(cctv_xinwenlianbo, "get", fake_get)
    monkeypatch.setattr(cctv_xinwenlianbo, "_today", lambda: "20260716")
    monkeypatch.setattr(cctv_xinwenlianbo, "_previous_day", lambda day: day)
    await cctv_xinwenlianbo.handle_route(_request(b"day=../../etc/passwd"))
