from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import v2ex_feeds
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/v2ex-feeds",
        "query_string": query,
        "headers": [],
    })


def _entry(
    title: str,
    href: str,
    *,
    published: str = "2026-09-22T07:19:37Z",
    author: str = "iflint",
    content: str = "",
) -> str:
    return (
        "<entry>"
        f"<title>{title}</title>"
        f'<link rel="alternate" type="text/html" href="{href}" />'
        "<id>tag:www.v2ex.com,2026-09-22:/t/1</id>"
        f"<published>{published}</published>"
        f"<author><name>{author}</name></author>"
        f'<content type="html"><![CDATA[{content}]]></content>'
        "</entry>"
    )


def _atom(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>Android</title>"
        '<link rel="self" type="application/atom+xml" href="https://www.v2ex.com/feed/android.xml" />'
        "<updated>2026-09-22T07:18:37Z</updated>"
        f"{entries}"
        "</feed>"
    )


@pytest.mark.asyncio
async def test_node_board_maps_topic_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        xml = _atom(
            _entry(
                "主题一",
                "https://www.v2ex.com/t/1243976#reply4",
                content="<p>正文一</p><p><img src='https://cdn.v2ex.com/a.png' /></p>",
            )
            + _entry("主题二", "https://www.v2ex.com/t/1243776#reply0", author="jim9606")
        )
        return RequestResult(False, "2026-10-01T00:00:00+00:00", xml)

    monkeypatch.setattr(v2ex_feeds, "get", fake_get)
    result = await v2ex_feeds.handle_route(_request("node-android"), no_cache=True)

    assert captured["url"] == "https://www.v2ex.com/feed/android.xml"
    # 如实表明是程序:不覆盖 User-Agent,httpx 缺省 UA 即 python-httpx/<版本>
    assert captured["headers"].get("User-Agent") is None
    assert result.name == "v2ex-feeds"
    assert result.type == "节点 · Android"
    assert result.link == "https://www.v2ex.com/go/android"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "1243976"  # 主题号作 id,不是 feed 的 tag: URI
    assert first.title == "主题一"
    assert first.url == "https://www.v2ex.com/t/1243976"  # 去掉 #reply 锚点
    assert first.mobileUrl == first.url
    assert first.hot == 4  # 锚点里的回复数
    assert first.author == "iflint"
    assert first.desc == "正文一"
    assert first.cover == "https://cdn.v2ex.com/a.png"
    expected_ms = int(datetime(2026, 9, 22, 7, 19, 37, tzinfo=UTC).timestamp() * 1000)
    assert first.timestamp == expected_ms  # published(UTC) -> 毫秒
    second = result.data[1]
    assert second.hot == 0  # #reply0 也是有效回复数
    assert second.desc is None  # 空正文 -> 空


@pytest.mark.asyncio
async def test_feed_order_is_preserved_not_resorted(monkeypatch):
    # tab 按最后回复排序,feed 顺序与 published 顺序可以不同;必须保留 feed 原顺序
    xml = _atom(
        _entry("旧帖", "https://www.v2ex.com/t/100#reply1", published="2026-09-20T10:00:00Z")
        + _entry("新帖", "https://www.v2ex.com/t/200#reply2", published="2026-09-22T10:00:00Z")
    )

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://www.v2ex.com/feed/tab/tech.xml"
        return RequestResult(False, "t", xml)

    monkeypatch.setattr(v2ex_feeds, "get", fake_get)
    result = await v2ex_feeds.handle_route(_request("tab-tech"), no_cache=True)

    assert result.type == "首页 · 技术"
    assert result.link == "https://www.v2ex.com/?tab=tech"
    assert [item.id for item in result.data] == ["100", "200"]  # feed 原顺序,未按时间重排
    assert [item.title for item in result.data] == ["旧帖", "新帖"]


@pytest.mark.asyncio
async def test_member_board_keeps_prefix_and_page(monkeypatch):
    xml = _atom(
        _entry("[python] 会员主题", "https://www.v2ex.com/t/999#reply12", author="qiayue")
    )

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://www.v2ex.com/feed/member/qiayue.xml"
        return RequestResult(False, "t", xml)

    monkeypatch.setattr(v2ex_feeds, "get", fake_get)
    result = await v2ex_feeds.handle_route(_request("member-qiayue"), no_cache=True)

    assert result.type == "会员 · qiayue"
    assert result.link == "https://www.v2ex.com/member/qiayue/topics"
    item = result.data[0]
    assert item.title == "[python] 会员主题"  # "[节点] " 前缀照 feed 原样保留
    assert item.author == "qiayue"
    assert item.hot == 12


@pytest.mark.asyncio
async def test_unmatched_link_keeps_url_and_drops_hot(monkeypatch):
    xml = _atom(_entry("推广帖", "https://www.v2ex.com/go/promotion"))

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", xml)

    monkeypatch.setattr(v2ex_feeds, "get", fake_get)
    result = await v2ex_feeds.handle_route(_request("node-openai"), no_cache=True)

    item = result.data[0]
    assert item.url == "https://www.v2ex.com/go/promotion"  # 链接形态变了:原样输出
    assert item.id == "https://www.v2ex.com/go/promotion"
    assert item.hot is None  # 没有锚点就没有回复数
    assert result.link == "https://www.v2ex.com/go/openai"


@pytest.mark.asyncio
async def test_default_board_is_first_declared_type(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _atom(_entry("默认榜", "https://www.v2ex.com/t/1#reply0")))

    monkeypatch.setattr(v2ex_feeds, "get", fake_get)
    request = _request(None)
    result = await v2ex_feeds.handle_route(request, no_cache=True)

    first_type = next(iter(v2ex_feeds.type_map))
    assert first_type == "node-android"  # 声明序第一个是默认榜
    assert result.type == v2ex_feeds.type_map[first_type]
    assert result.total == 1


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await v2ex_feeds.handle_route(_request("hot"), no_cache=True)  # hot 属于 v2ex 路由


@pytest.mark.asyncio
async def test_challenge_page_and_empty_feed_raise(monkeypatch):
    async def fake_challenge(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><title>Just a moment...</title></html>")

    async def fake_empty(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _atom(""))

    monkeypatch.setattr(v2ex_feeds, "get", fake_challenge)
    with pytest.raises(RuntimeError, match="Cloudflare challenge"):
        await v2ex_feeds.handle_route(_request("node-bb"), no_cache=True)

    monkeypatch.setattr(v2ex_feeds, "get", fake_empty)
    with pytest.raises(RuntimeError, match="parsed no entries"):
        await v2ex_feeds.handle_route(_request("node-bb"), no_cache=True)
