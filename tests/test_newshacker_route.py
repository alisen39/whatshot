from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import newshacker_zh
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/newshacker-zh",
        "query_string": b"type=hot",
        "headers": [],
    })


def _meta_description(score: int, author: str, summary: str) -> str:
    return (
        f"&lt;p&gt;&lt;strong&gt;评分:&lt;/strong&gt; {score} | &lt;strong&gt;作者:&lt;/strong&gt; {author}&lt;/p&gt;"
        f"&lt;p&gt;{summary}&lt;/p&gt;"
    )


def _rss_item(guid: str, title: str, pub_date: str, description: str) -> str:
    return (
        f"<item><guid>{guid}</guid><title>{title}</title>"
        f"<link>https://newshacker.me/story?id={guid}</link>"
        f"<pubDate>{pub_date}</pubDate><description>{description}</description></item>"
    )


RSS_SAMPLE = (
    "<rss><channel>"
    "<title>News Hacker</title>"
    + _rss_item("49800001", "📺 标题一", "Wed, 30 Sep 2026 12:00:00 GMT",
                _meta_description(24, "papergirl", "讨论摘要一"))
    + _rss_item("49800002", "💸 标题二", "Wed, 30 Sep 2026 10:00:00 GMT",
                _meta_description(132, "user2", "讨论摘要二"))
    + _rss_item("49800003", "🛠 标题三", "Wed, 30 Sep 2026 08:00:00 GMT",
                "&lt;p&gt;只有正文,没有评分与作者段落&lt;/p&gt;")
    + "</channel></rss>"
)


@pytest.mark.asyncio
async def test_parses_feed_and_enriches_score_author(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["no_cache"] = no_cache
        return RequestResult(False, "2026-10-01T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(newshacker_zh, "get", fake_get)
    result = await newshacker_zh.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://api.newshacker.me/rss"
    assert result.name == "newshacker-zh"
    assert result.type == "中文精选"
    assert result.total == 3
    first = result.data[0]
    assert first.id == "49800001"
    assert first.title == "📺 标题一"
    assert first.url == "https://newshacker.me/story?id=49800001"
    assert first.hot == 24
    assert first.author == "papergirl"
    assert first.timestamp == 1790769600000  # 2026-09-30 12:00 UTC,毫秒
    assert "讨论摘要一" in (first.desc or "")
    # 第三条 description 里没有"评分 / 作者"段落,字段留空,其余不受影响
    third = result.data[2]
    assert third.id == "49800003"
    assert third.hot is None
    assert third.author is None
    # feed 本身按摘要生成时间倒序,parse_feed 的时间排序不改变顺序
    assert [i.id for i in result.data] == ["49800001", "49800002", "49800003"]


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "2026-10-01T00:00:00+00:00", "<rss><channel></channel></rss>")

    monkeypatch.setattr(newshacker_zh, "get", fake_get)
    with pytest.raises(RuntimeError, match="did not contain any items"):
        await newshacker_zh.handle_route(_request(), no_cache=True)
