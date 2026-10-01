from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import kr36
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/36kr",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _entry(item_id: str, **material) -> dict:
    return {"itemId": item_id, "templateMaterial": {"widgetTitle": f"条目{item_id}", **material}}


@pytest.mark.asyncio
async def test_video_board_uses_stat_read_and_video_link(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", {
            "data": {"videoList": [_entry("6001", statRead=20448, statCollect=None)]}
        })

    monkeypatch.setattr(kr36, "post", fake_post)
    result = await kr36.handle_route(_request("video"), no_cache=True)

    assert captured["url"].endswith("/nav/rank/video")
    item = result.data[0]
    assert item.hot == 20448  # 视频条目没有 statCollect,取 statRead
    assert item.url == "https://www.36kr.com/video/6001"  # 不是文章链接 /p/
    assert item.mobileUrl == "https://m.36kr.com/video/6001"


@pytest.mark.asyncio
async def test_hot_board_keeps_collect_stat_and_article_link(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"data": {"hotRankList": [_entry("6002", statCollect=77)]}})

    monkeypatch.setattr(kr36, "post", fake_post)
    result = await kr36.handle_route(_request("hot"), no_cache=True)

    item = result.data[0]
    assert item.hot == 77
    assert item.url == "https://www.36kr.com/p/6002"
