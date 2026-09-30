from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import acfun
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str, rng: str | None = None) -> Request:
    query = f"type={board_type}"
    if rng:
        query = f"{query}&range={rng}"
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/acfun",
        "query_string": query.encode(),
        "headers": [],
    })


def _video(douga_id: str, like: int) -> dict:
    return {
        "dougaId": douga_id,
        "contentTitle": f"视频{douga_id}",
        "contentDesc": "简介",
        "coverUrl": "https://img.acfun.cn/c.jpg",
        "userName": "UP主",
        "contributeTime": 1759190400000,
        "likeCount": like,
        "viewCount": like * 10,
        "shareUrl": f"https://m.acfun.cn/v/?ac={douga_id}",
    }


def _article(content_id: str, view: int) -> dict:
    return {
        "contentId": content_id,
        "contentTitle": f"文章{content_id}",
        "contentDesc": "<br/>文章摘要<br/>",
        "coverUrl": "https://img.acfun.cn/a.jpg",
        "userName": "作者",
        "contributeTime": 1759190400000,
        "viewCount": view,
        "shareUrl": f"https://m.acfun.cn/a/?ac={content_id}",
    }


@pytest.mark.asyncio
async def test_sends_browser_ua_and_propagates_no_cache(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["no_cache"] = no_cache
        return RequestResult(False, "t", {"rankList": []})

    monkeypatch.setattr(acfun, "get", fake_get)
    await acfun.handle_route(_request("-1"), no_cache=True)

    assert captured["no_cache"] is True
    assert captured["url"] == (
        "https://www.acfun.cn/rest/pc-direct/rank/channel?channelId=&rankLimit=30&rankPeriod=DAY"
    )
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert "Referer" in captured["headers"]


@pytest.mark.asyncio
async def test_video_entries_keep_existing_field_semantics(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"rankList": [_video("48875209", 321)]})

    monkeypatch.setattr(acfun, "get", fake_get)
    result = await acfun.handle_route(_request("1"), no_cache=True)

    assert result.type == "排行榜 · 动画"
    item = result.data[0]
    assert item.id == "48875209"
    assert item.hot == 321  # 视频沿用点赞数,与既有口径一致
    assert item.url == "https://www.acfun.cn/v/ac48875209"
    assert item.mobileUrl == "https://m.acfun.cn/v/?ac=48875209"


@pytest.mark.asyncio
async def test_article_entries_use_content_id_and_view_count(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"rankList": [_article("13059721", 5217)]})

    monkeypatch.setattr(acfun, "get", fake_get)
    result = await acfun.handle_route(_request("63"), no_cache=True)

    assert result.type == "排行榜 · 文章"
    item = result.data[0]
    assert item.id == "13059721"
    assert item.hot == 5217  # 文章没有 likeCount,取页面卡片显示的 viewCount
    assert item.url == "https://www.acfun.cn/a/ac13059721"
    assert item.mobileUrl == "https://m.acfun.cn/a/?ac=13059721"
    assert item.desc == "文章摘要"  # 去掉 <br/> 等 HTML
    assert "<" not in (item.desc or "")


@pytest.mark.asyncio
async def test_article_entry_without_share_url_falls_back(monkeypatch):
    entry = _article("13059722", 10)
    entry.pop("shareUrl")

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"rankList": [entry]})

    monkeypatch.setattr(acfun, "get", fake_get)
    result = await acfun.handle_route(_request("63"), no_cache=True)

    assert result.data[0].mobileUrl == "https://m.acfun.cn/v/?ac=13059722"


@pytest.mark.asyncio
async def test_missing_upstream_item_root_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"error": "denied"})

    monkeypatch.setattr(acfun, "get", fake_get)
    with pytest.raises((KeyError, TypeError)):
        await acfun.handle_route(_request("-1"), no_cache=True)
