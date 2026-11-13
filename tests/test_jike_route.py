"""jike 路由测试：圈子页 __NEXT_DATA__ 结构依 board_api 证据（08_jike_topic_ai_explore）净化内联。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import jike
from whats_hot_api.utils.http_client import RequestResult


def _request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": query_string, "headers": []})


def _fake_get(props: dict, captured: dict):
    page = (
        '<!DOCTYPE html><html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": props}}, ensure_ascii=False)
        + "</script></head><body></body></html>"
    )

    async def handler(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-11-12T00:00:00+00:00", page)

    return handler


@pytest.mark.asyncio
async def test_jike_maps_posts_to_newsflash(monkeypatch):
    captured: dict = {}
    props = {
        "topic": {"id": "63579abb6724cc583b9bba9a", "name": "AI探索站"},
        "posts": [
            {"id": "bbbb", "content": "长" * 90, "type": "REPOST", "likeCount": 3,
             "createdAt": "2026-09-24T08:00:00.000Z", "user": None,
             "pictures": [{"picUrl": "https://i9.taou.com/pic.jpg"}]},
            {"id": "6ab69e93141b85b2926a94eb", "content": "第一行是标题\n第二行正文", "type": "ORIGINAL_POST",
             "likeCount": 46, "createdAt": "2026-09-25T16:17:23.420Z",
             "user": {"screenName": "郦橙锦妖Vanessa"}, "pictures": []},
            {"id": "no-content", "content": "", "likeCount": 2},
        ],
    }
    monkeypatch.setattr(jike, "get", _fake_get(props, captured))
    result = await jike.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://m.okjike.com/topics/63579abb6724cc583b9bba9a"  # 默认圈子：AI探索站
    assert (result.kind, result.name, result.title, result.type) == ("newsflash", "jike", "即刻", "AI探索站")
    first, second = result.data  # 按发帖时间倒序；空帖跳过
    assert first.id == "6ab69e93141b85b2926a94eb"
    assert first.title == "第一行是标题"  # 帖子没有标题，取正文第一行
    assert first.content == "第二行正文"  # 第一行已作标题，正文里不再重复
    assert first.url == "https://m.okjike.com/originalPosts/6ab69e93141b85b2926a94eb"
    assert first.source == "郦橙锦妖Vanessa"
    assert first.metrics == {"likes": 46}
    assert first.timestamp == int(datetime(2026, 9, 25, 16, 17, 23, 420000, tzinfo=UTC).timestamp() * 1000)
    assert second.url == "https://m.okjike.com/reposts/bbbb"  # REPOST → reposts 路径
    assert second.title == "长" * 80 + "…"  # 超 80 字截断
    assert second.content == "长" * 90  # 标题被截断时保留全文
    assert second.images == ["https://i9.taou.com/pic.jpg"]
    assert second.source == "AI探索站"  # 没有作者时用圈子名


@pytest.mark.asyncio
async def test_jike_circles_are_types(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(jike, "get", _fake_get({"posts": [{"id": "1", "content": "正文"}]}, captured))
    result = await jike.handle_route(_request(b"type=pm-daily"), no_cache=True)

    assert captured["url"] == "https://m.okjike.com/topics/563a2995306dab1300a32227"
    assert result.type == "产品经理的日常"
    assert list(jike.ROUTE_META["params"]["type"]["type"]) == ["ai-explore", "pm-daily"]


@pytest.mark.asyncio
async def test_jike_page_without_posts_fails(monkeypatch):
    monkeypatch.setattr(jike, "get", _fake_get({"topic": {}}, {}))
    with pytest.raises(RuntimeError, match="no posts list"):
        await jike.handle_route(_request(), no_cache=True)
