from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_book_extra
from whats_hot_api.utils.http_client import RequestResult

# 从 evidence/01_feed_review_book.response.body 净化：保留 <item> 结构
# （title "(评论: <书名>)" 形、description CDATA = 头部一段 + 截断的 Draft.js JSON、
# content:encoded 书封、dc:creator、pubDate、guid）。顺序照 feed：第 2 条比第 1 条旧，
# 证明顺序是"最受欢迎"的名次、不是时间序
_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>豆瓣最受欢迎的书评</title>
  <link>https://book.douban.com/review/book_best/</link>

    <item>
        <title>《甜蜜毒药》民翻译本勘误 (评论: Sweet Poison)</title>
        <link>https://book.douban.com/review/17829641/</link>
        <description><![CDATA[
幼稚园的小黑评论: Sweet Poison (https://book.douban.com/subject/3645508/)
评价: 力荐

{&#34;entityMap&#34;: {}, &#34;blocks&#34;: [{&#34;key&#34;: &#34;1&#34;, &#34;text&#34;: &#34;\\u672c\\u4e66\\u8bc4\\u5206\\u4e94\\u661f\\u3002\\u8fd8\\u6709\\u4e00\\u4e9b...&#34;}, {&#34;key&#34;: &#34;2&#34;, &#34;text&#34;: &#34;\\u7b2c\\u4e8c\\u6bb5\\u88ab\\u622a\\u65ad&#34;},
]]></description>
        <content:encoded><![CDATA[
<img src="https://img9.doubanio.com/view/subject/m/public/s3704655.jpg" style="float:right"/>
]]></content:encoded>
        <dc:creator>幼稚园的小黑</dc:creator>
        <pubDate>Fri, 25 Sep 2026 11:02:06 GMT</pubDate>
        <guid isPermaLink="true">https://book.douban.com/review/17829641/</guid>
    </item>

    <item>
        <title>后记 (评论: 普通炎症)</title>
        <link>https://book.douban.com/review/17823711/</link>
        <description><![CDATA[
脱陀妥浮伺机评论: 普通炎症 (https://book.douban.com/subject/38543160/)
评价: 推荐

{&#34;blocks&#34;:[{&#34;key&#34;:&#34;67sd&#34;,&#34;text&#34;:&#34;\\u5ff5\\u5c0f\\u5b66\\u7684\\u67d0\\u4e00\\u5929...&#34;},
]]></description>
        <content:encoded><![CDATA[
<img src="https://img3.doubanio.com/view/subject/m/public/s35617119.jpg" style="float:right"/>
]]></content:encoded>
        <dc:creator>脱陀妥浮伺机</dc:creator>
        <pubDate>Sun, 20 Sep 2026 10:15:42 GMT</pubDate>
        <guid isPermaLink="true">https://book.douban.com/review/17823711/</guid>
    </item>
</channel>
</rss>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/douban-book-extra",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_feed_maps_all_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _FEED_XML)

    monkeypatch.setattr(douban_book_extra, "get", fake_get)
    result = await douban_book_extra.handle_route(_request("review-best"), no_cache=True)

    assert captured["url"] == "https://www.douban.com/feed/review/book"
    # probe.log：python-httpx 缺省 UA 被 418，必须带浏览器 UA
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]

    assert result.type == "最受欢迎的书评"
    assert result.total == 2
    # channel link 是 PC 榜单页
    assert result.link == "https://book.douban.com/review/book_best/"
    item = result.data[0]
    assert item.id == "17829641"
    assert item.title == "《甜蜜毒药》民翻译本勘误 (评论: Sweet Poison)"
    assert item.url == "https://book.douban.com/review/17829641/"
    assert item.mobileUrl == "https://m.douban.com/book/review/17829641/"
    assert item.author == "幼稚园的小黑"
    assert item.cover == "https://img9.doubanio.com/view/subject/m/public/s3704655.jpg"
    # desc = 头部一段（去掉书链接）+ Draft.js 各段 text（含被截断的最后一段，段间空格拼接）
    assert item.desc == "幼稚园的小黑评论: Sweet Poison 评价: 力荐 · 本书评分五星。还有一些 第二段被截断"
    assert item.timestamp == 1790334126000  # Fri, 25 Sep 2026 11:02:06 GMT 转毫秒
    # RSS 没有有用数，hot 留空
    assert item.hot is None


@pytest.mark.asyncio
async def test_feed_order_is_preserved_not_time_sorted(monkeypatch):
    """书评 RSS 不是按时间排的（第 2 条比第 1 条旧），是"最受欢迎"的名次，不重排。"""

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(True, "t", _FEED_XML)

    monkeypatch.setattr(douban_book_extra, "get", fake_get)
    result = await douban_book_extra.handle_route(_request("review-best"), no_cache=False)
    assert [item.id for item in result.data] == ["17829641", "17823711"]
    assert result.fromCache is True


@pytest.mark.asyncio
async def test_bad_pubdate_and_missing_cover_do_not_crash(monkeypatch):
    broken = _FEED_XML.replace("Fri, 25 Sep 2026 11:02:06 GMT", "").replace(
        '<img src="https://img3.doubanio.com/view/subject/m/public/s35617119.jpg" style="float:right"/>', ""
    )

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", broken)

    monkeypatch.setattr(douban_book_extra, "get", fake_get)
    result = await douban_book_extra.handle_route(_request("review-best"), no_cache=True)
    assert result.data[0].timestamp is None
    assert result.data[1].cover is None


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<rss version='2.0'><channel></channel></rss>")

    monkeypatch.setattr(douban_book_extra, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await douban_book_extra.handle_route(_request("review-best"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        raise AssertionError("unknown type must not hit upstream")

    monkeypatch.setattr(douban_book_extra, "get", fake_get)
    # 新书速递 / 畅销图书榜受阻不迁；影评 RSS 属于 douban-charts 的 review-best，不在这个路由
    with pytest.raises(ValueError, match="Unknown board"):
        await douban_book_extra.handle_route(_request("latest"), no_cache=True)
