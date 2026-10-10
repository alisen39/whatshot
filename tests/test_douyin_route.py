from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douyin
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/douyin",
        "query_string": b"type=hot",
        "headers": [],
    })


SAMPLE = {
    "data": {
        "word_list": [
            {"sentence_id": "7001", "word": "置顶话题", "word_type": 14, "hot_value": 0, "event_time": 1790769600},
            {"sentence_id": "7002", "word": "热搜第一", "word_type": 1, "hot_value": 9876543, "event_time": 1790769500},
        ]
    }
}


@pytest.mark.asyncio
async def test_fetches_without_cookie_bootstrap_and_keeps_version_name(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", SAMPLE)

    monkeypatch.setattr(douyin, "get", fake_get)
    result = await douyin.handle_route(_request(), no_cache=True)

    # 修复点:不再请求 login_guiding_strategy 取 cookie(该步骤被风控拦截);
    # URL 带 version_name(缺失时上游只回 48~49 条且名次错位),带浏览器 UA 与 Referer
    assert captured["url"].startswith("https://www.douyin.com/aweme/v1/web/hot/search/list/")
    assert "version_name=17.4.0" in captured["url"]
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert captured["headers"]["Referer"]
    assert captured["no_cache"] is True

    assert result.total == 2
    pinned, first = result.data
    assert pinned.id == "7001"
    assert pinned.isPinned is True
    assert pinned.sourceRank is None
    assert pinned.hot == 0
    assert pinned.timestamp == 1790769600000  # 秒级补毫秒
    assert first.title == "热搜第一"
    assert first.hot == 9876543
    assert first.url == "https://www.douyin.com/hot/7002"


@pytest.mark.asyncio
async def test_empty_word_list_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", {"data": {}})

    monkeypatch.setattr(douyin, "get", fake_get)
    with pytest.raises(RuntimeError, match="returned no entries"):
        await douyin.handle_route(_request(), no_cache=True)
