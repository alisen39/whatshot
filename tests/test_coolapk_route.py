"""coolapk 路由测试(修复+扩 4 榜):mock 共享 get,fixtures 从 board_api 证据净化。

覆盖:App Dalvik UA 与 token 头、dataList 列表地址拼接(rank_score 口径)、
条目字段映射(标题截断/entityType 过滤/酷图链接)、错误壳拒绝、未知子榜。
"""
from __future__ import annotations

import re

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import coolapk as route
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/coolapk",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


_UPDATE_TIME = "2026-10-01T00:00:00+00:00"
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}[0-9a-z-]{46}0x[0-9a-f]+$")


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


@pytest.mark.asyncio
async def test_coolapk_today_uses_app_ua_token_and_rank_score_url(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        rows = [
            _feed_row(74069448, "正文内容一条", 1790691488, pic="http://image.coolapk.com/a.jpg"),
            {  # 广告卡片：不算条目
                "id": 74069449,
                "entityType": "card",
                "sponsorCard": {"title": "广告"},
            },
            _feed_row(74069448, "重复动态", 1790691488),
        ]
        return RequestResult(False, _UPDATE_TIME, {"data": rows})

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("today"), no_cache=True)

    # 需修点 1：必须是 App 的 Dalvik UA（含 +CoolMarket 标识），token 按 App 算法现算
    assert captured["headers"]["User-Agent"].startswith("Dalvik/")
    assert "+CoolMarket/11.0-2101202" in captured["headers"]["User-Agent"]
    assert _TOKEN_RE.match(captured["headers"]["X-App-Token"])  # md5 + 设备号 + 0x十六进制秒
    assert captured["headers"]["X-App-Id"] == "com.coolapk.market"
    assert captured["headers"]["X-Requested-With"] == "XMLHttpRequest"
    # 需修点 2：今日热门列表地址用 App 现行的 rank_score（不再是旧参数 detailnum）
    assert "url=%23%2Ffeed%2FstatList" in captured["url"]
    assert "sortField%3Drank_score" in captured["url"]
    assert "detailnum" not in captured["url"]
    assert "title=%E4%BB%8A%E6%97%A5%E7%83%AD%E9%97%A8" in captured["url"]
    assert captured["url"].endswith("&page=1")
    # 广告卡片与重复 id 被去掉
    assert [item.id for item in result.data] == ["74069448"]
    item = result.data[0]
    assert item.title == "正文内容一条"
    assert item.url == "https://www.coolapk.com/feed/74069448"
    assert item.cover == "http://image.coolapk.com/a.jpg"
    assert item.author == "酷安用户"
    assert item.hot is None  # 列表不按显示数字排序，hot 留空
    assert item.timestamp == 1790691488000  # dateline 秒 → 毫秒




@pytest.mark.asyncio
async def test_coolapk_headline_list_address_and_message_fallback(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured["url"] = url
        long_text = "<a class='feed-link-tag' href='/t/酷安夜话'>#酷安夜话#</a>" + "动态" * 80
        rows = [
            _feed_row(73914060, long_text, 1790690000, picArr=["http://image.coolapk.com/1.jpg"]),
            _feed_row(73910683, "带标题动态", 1790680000, message_title="这是标题"),
        ]
        return RequestResult(False, _UPDATE_TIME, {"data": rows})

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("headline"), no_cache=True)

    # RSSHub「历史头条」对应的 App 列表地址
    assert "url=%23%2Ffeed%2FheadlineV8List" in captured["url"]
    assert "type%3D0%2C5%2C9%2C8%2C12%2C10%2C11%2C13" in captured["url"]
    first = result.data[0]
    assert first.id == "73914060"
    # 无标题动态：标题取正文去 HTML 的前 120 字加截断号（get_text 在节点间补空格）
    assert first.title == ("#酷安夜话# " + "动态" * 80)[:120] + "…"
    assert len(first.title) == 121
    assert first.desc == "#酷安夜话# " + "动态" * 80  # 与标题不同，正文前 500 字
    assert first.cover == "http://image.coolapk.com/1.jpg"  # pic 为空时取 picArr[0]
    second = result.data[1]
    assert second.title == "这是标题"  # message_title 优先
    assert second.desc == "带标题动态"




@pytest.mark.asyncio
async def test_coolapk_rejects_non_list_and_empty_and_unknown_board(monkeypatch):
    async def fake_status_shell(url, headers=None, params=None, no_cache=None, **kwargs):
        # token 失效时服务端返回业务错误壳（status=1005 请求已过期）
        return RequestResult(False, _UPDATE_TIME, {"status": 1005, "message": "请求已过期"})

    monkeypatch.setattr(route, "get", fake_status_shell)
    with pytest.raises(RuntimeError, match="returned no data list"):
        await route.handle_route(_request("reply"), no_cache=True)

    async def fake_empty(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"data": [{"entityType": "card"}]})

    monkeypatch.setattr(route, "get", fake_empty)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await route.handle_route(_request("kutu"), no_cache=True)

    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)

