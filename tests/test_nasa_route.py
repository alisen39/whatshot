"""nasa 路由测试:fixtures 按证据目录 tmp/board_api/nasa 净化(结构与字段与
evidence/01_news_feed、03_iotd_feed 一致,内容摘录改写,不含抓包原文)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nasa
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-09-27T00:00:00+00:00"

# ---- news(WordPress feed:guid 多为 ?p=文章号,dc:creator,APOD 条目 guid 是链接本身且无作者) ----

_NEWS_RSS = """<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel><title>NASA</title><link>https://www.nasa.gov</link>
<item><title>NASA Welcomes San Marino Signing the Artemis Accords</title>
<link>https://www.nasa.gov/organizations/oiir/nasa-welcomes-san-marino/</link>
<guid isPermaLink="false">https://www.nasa.gov/?p=1050600</guid>
<dc:creator>Elizabeth Shaw</dc:creator>
<pubDate>Sun, 27 Sep 2026 13:14:43 +0000</pubDate>
<description><![CDATA[<p>The Republic of San Marino became the 76th signatory.</p>]]></description>
</item>
<item><title>APOD: Andromeda</title>
<link>https://science.nasa.gov/image-article/apod-2026-september-27-andromeda/</link>
<guid isPermaLink="false">https://science.nasa.gov/image-article/apod-2026-september-27-andromeda/</guid>
<pubDate>Sat, 26 Sep 2026 04:05:00 +0000</pubDate>
<description>APOD Science APOD: Andromeda picture of the day.</description>
</item>
</channel></rss>
"""

# ---- image-of-the-day(WordPress iotd feed:guid 即链接,author 取自 <source>,enclosure 配图) ----

_IOTD_RSS = """<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
<channel><title>NASA Image of the Day</title><link>https://www.nasa.gov</link>
<item><title>Hubble Spots Chaotic Secret in Galaxy</title>
<link>https://www.nasa.gov/image-detail/a-galaxy-spinning-out-of-sync/</link>
<guid isPermaLink="true">https://www.nasa.gov/image-detail/a-galaxy-spinning-out-of-sync/</guid>
<pubDate>Fri, 25 Sep 2026 15:54 GMT</pubDate>
<description>Though the spiral galaxy seems serene, it holds a chaotic secret.</description>
<source url="https://www.nasa.gov/feeds/iotd-feed/">NASA Image of the Day</source>
<enclosure url="https://www.nasa.gov/wp-content/uploads/2026/09/galaxy.jpg" type="image/jpeg" length="0"/>
</item>
<item><title>Older Image of the Day</title>
<link>https://www.nasa.gov/image-detail/older-image/</link>
<guid isPermaLink="true">https://www.nasa.gov/image-detail/older-image/</guid>
<pubDate>Thu, 24 Sep 2026 15:54 GMT</pubDate>
<description>Yesterday's picture.</description>
<source url="https://www.nasa.gov/feeds/iotd-feed/">NASA Image of the Day</source>
</item>
</channel></rss>
"""


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/nasa",
        "query_string": query,
        "headers": [],
    })


def _mock(monkeypatch, body: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake_get(**kwargs):
        seen.update(kwargs)
        return RequestResult(False, _UPDATE_TIME, body)

    monkeypatch.setattr(nasa, "get", fake_get)
    return seen


async def test_news_is_default_board_and_maps_fields(monkeypatch):
    seen = _mock(monkeypatch, _NEWS_RSS)
    result = await nasa.handle_route(_request(), no_cache=True)

    assert seen["url"] == "https://www.nasa.gov/feed/"
    assert seen["no_cache"] is True
    assert result.name == "nasa"
    assert result.type == "News"  # 缺省 news
    assert result.title == "NASA"
    assert result.link == "https://www.nasa.gov/"
    assert result.total == 2
    first, second = result.data
    assert first.id == "https://www.nasa.gov/?p=1050600"  # guid
    assert first.title == "NASA Welcomes San Marino Signing the Artemis Accords"
    assert first.url == first.mobileUrl == "https://www.nasa.gov/organizations/oiir/nasa-welcomes-san-marino/"
    assert first.author == "Elizabeth Shaw"  # dc:creator
    assert first.desc == "The Republic of San Marino became the 76th signatory."  # 去 HTML
    assert first.cover is None  # feed 没有 media:*/enclosure,题图只在正文里,parse_feed 不取
    assert first.hot is None
    assert first.timestamp == int(datetime(2026, 9, 27, 13, 14, 43, tzinfo=UTC).timestamp() * 1000)
    # APOD 条目:guid 是链接本身、无作者,desc 是 feed 自带摘要原样输出
    assert second.id == "https://science.nasa.gov/image-article/apod-2026-september-27-andromeda/"
    assert second.author is None
    assert second.timestamp == int(datetime(2026, 9, 26, 4, 5, 0, tzinfo=UTC).timestamp() * 1000)
    # feed 原顺序(新的在前)不重排
    assert [item.id for item in result.data] == [first.id, second.id]


async def test_image_of_the_day_maps_cover_and_source_author(monkeypatch):
    seen = _mock(monkeypatch, _IOTD_RSS)
    result = await nasa.handle_route(_request("image-of-the-day"), no_cache=True)

    assert seen["url"] == "https://www.nasa.gov/feeds/iotd-feed/"
    assert result.type == "每日一图"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://www.nasa.gov/image-detail/a-galaxy-spinning-out-of-sync/"  # guid 即链接
    assert first.url == first.id
    assert first.author == "NASA Image of the Day"  # feed 无作者,parse_feed 回退到 <source>
    assert first.cover == "https://www.nasa.gov/wp-content/uploads/2026/09/galaxy.jpg"  # enclosure
    # pubDate 无秒(Fri, 25 Sep 2026 15:54 GMT)→ 毫秒
    assert first.timestamp == int(datetime(2026, 9, 25, 15, 54, tzinfo=UTC).timestamp() * 1000)
    assert result.data[1].cover is None  # 没有 enclosure 的条目不填


async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await nasa.handle_route(_request("nope"), no_cache=True)


async def test_empty_feed_is_an_error(monkeypatch):
    _mock(monkeypatch, "<html>blocked</html>")
    with pytest.raises(RuntimeError, match="returned no items"):
        await nasa.handle_route(_request("news"), no_cache=True)


async def test_cached_result_propagates_from_cache(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(True, _UPDATE_TIME, _NEWS_RSS)

    monkeypatch.setattr(nasa, "get", fake_get)
    result = await nasa.handle_route(_request("news"), no_cache=False)

    assert result.fromCache is True
    assert result.updateTime == _UPDATE_TIME
