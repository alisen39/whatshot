"""sspai-extra 路由测试：mock 共享 get，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

import re

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import sspai_extra as route
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-09-30T13:00:00+00:00"
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}[0-9a-z-]{46}0x[0-9a-f]+$")

def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/sspai-extra",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )

def _article(item_id: str, title: str, released: str, **extra) -> dict:
    return {
        "id": item_id,
        "title": title,
        "summary": "摘要文本",
        "banner": "2026/9/30/article/abc.jpeg",
        "released_time": released,
        "like_count": "9",
        "belong_to_member": False,
        "slug": "",
        "important": 1,
        "author": {"nickname": "少数派编辑部"},
        "advertisement_url": "",
        **extra,
    }

def _sspai_envelope(rows: list[dict]) -> dict:
    return {"error": 0, "msg": "", "data": rows}

def _feed_row(feed_id: int, message: str, dateline: int, **extra) -> dict:
    return {
        "id": feed_id,
        "entityType": "feed",
        "message_title": "",
        "message": message,
        "url": f"/feed/{feed_id}",
        "pic": "",
        "picArr": [],
        "dateline": dateline,
        "username": "酷安用户",
        **extra,
    }

# ---------------------------------------------------------------- 少数派

@pytest.mark.asyncio
async def test_sspai_latest_maps_fields_and_adjusts_leading_important(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers})
        # 第 1 篇是大卡片（important=2），页面会把它与后面第一篇普通文章对调
        rows = [
            _article("115166", "大卡片文章", "1790751600", important=2),
            _article("115167", "普通文章", "1790751500"),
        ]
        return RequestResult(False, _UPDATE_TIME, _sspai_envelope(rows))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("sspai-latest"), no_cache=True)

    assert captured["url"] == "https://sspai.com/api/v1/article/index/page/get"
    assert captured["params"]["limit"] == "10"
    assert captured["params"]["created_at"] == "0"
    assert captured["headers"]["Accept"] == route._JSON_ACCEPT
    assert result.total == 2
    assert [item.id for item in result.data] == ["115167", "115166"]  # 对调生效
    first = result.data[0]
    assert first.title == "普通文章"
    assert first.url == "https://sspai.com/post/115167"
    assert first.mobileUrl == first.url
    assert first.hot == 9
    assert first.cover == "https://cdnfile.sspai.com/2026/9/30/article/abc.jpeg"
    assert first.author == "少数派编辑部"
    assert first.desc == "摘要文本"
    assert first.timestamp == 1790751500000  # 字符串秒级 → 毫秒
    assert result.fromCache is False
    assert result.updateTime == _UPDATE_TIME

@pytest.mark.asyncio
async def test_sspai_article_member_url_and_advertisement_skipped(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        rows = [
            _article("115200", "会员专栏文章", "1790750000", belong_to_member=True, slug="prime-slug"),
            _article("115201", "广告卡片", "1790740000", advertisement_url="https://sspai.com/ad/1"),
        ]
        return RequestResult(True, _UPDATE_TIME, _sspai_envelope(rows))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("sspai-latest"), no_cache=False)

    assert result.fromCache is True
    assert [item.id for item in result.data] == ["115200"]  # 广告卡片不算条目
    assert result.data[0].url == "https://sspai.com/prime/story/prime-slug"

@pytest.mark.asyncio
async def test_sspai_bullet_maps_created_at_and_participations(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params})
        rows = [
            {
                "title": "<p>聊聊你用开源项目替代了哪些付费订阅？</p>",
                "body": "<p>正文段落一</p><p>正文段落二</p>",
                "banner": "2026/9/23/article/bullet.jpg",
                "released_at": "1790751010",
                "created_at": "1790146393",
                "participations_count": 26,
                "authors": [{"nickname": "一派用户"}],
            }
        ]
        return RequestResult(False, _UPDATE_TIME, _sspai_envelope(rows))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("sspai-bullet"), no_cache=True)

    assert captured["url"] == "https://sspai.com/api/v1/bullet/search/page/get"
    assert captured["params"]["limit"] == "10"
    assert "created_at" in captured["params"]  # 页面用服务端渲染时刻的当前秒
    item = result.data[0]
    assert item.id == "1790146393"  # 一派没有 id 字段，链接用 created_at
    assert item.title == "聊聊你用开源项目替代了哪些付费订阅？"
    assert item.url == "https://sspai.com/bullet/1790146393"
    assert item.hot == 26  # 页面「N 位少数派已参与」
    assert item.author == "一派用户"
    assert item.desc == "正文段落一 正文段落二"
    assert item.timestamp == 1790751010000  # released_at：列表排序键

@pytest.mark.asyncio
async def test_sspai_series_uses_page_redirect_url(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        rows = [
            {
                "id": "422",
                "title": "中古掌机收藏选购指南",
                "banner": "2026/6/15/article/series.png",
                "released_at": "1785909661",
                "author": {"nickname": "专栏作者"},
                "page_redirect_url": "https://sspai.com/prime/series/422",
                "description": "给过去的自己一件礼物",
            }
        ]
        return RequestResult(False, _UPDATE_TIME, _sspai_envelope(rows))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("sspai-series"), no_cache=True)

    item = result.data[0]
    assert item.id == "422"
    assert item.url == "https://sspai.com/prime/series/422"  # page_redirect_url 优先
    assert item.author == "专栏作者"
    assert item.desc == "给过去的自己一件礼物"
    assert item.timestamp == 1785909661000  # 上架时间

@pytest.mark.asyncio
async def test_sspai_rejects_error_shell_empty_list_and_unknown_board(monkeypatch):
    async def fake_error(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"error": 40001, "msg": "token", "data": []})

    monkeypatch.setattr(route, "get", fake_error)
    with pytest.raises(RuntimeError, match="returned error=40001"):
        await route.handle_route(_request("sspai-zaobao"), no_cache=True)

    async def fake_empty(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, _sspai_envelope([]))

    monkeypatch.setattr(route, "get", fake_empty)
    with pytest.raises(RuntimeError, match="returned no items"):
        await route.handle_route(_request("sspai-matrix-hot"), no_cache=True)

    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)

# ---------------------------------------------------------------- 酷安

