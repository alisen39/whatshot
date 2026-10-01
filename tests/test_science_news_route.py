"""science_news 路由测试:fixtures 按证据目录 tmp/board_api/science_news 净化(结构与字段与
evidence/01_news_rss 的 RSS 1.0/RDF 一致,内容摘录改写,不含抓包原文)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import science_news
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-09-27T00:00:00+00:00"

# 文档顺序与时间顺序不一致(证据:feed 不按时间排,board_api 因此改为保留原顺序)
_RDF_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:enc="http://purl.oclc.org/net/rss_2.0/enc/"
         xmlns="http://purl.org/rss/1.0/">
<channel rdf:about="https://www.science.org">
<title>Latest News from Science Magazine</title>
<link>https://www.science.org</link>
</channel>
<item rdf:about="https://www.science.org/doi/10.1126/science.aaaa1111">
<title>New space telescope will reopen astronomers' view of the far-infrared</title>
<link>https://www.science.org/content/article/new-space-telescope-far-infrared</link>
<description>NASA's $1.2 billion PRIMA will explore how galaxies evolve.</description>
<enc:enclosure rdf:resource="https://www.science.org/do/10.1126/science.aaaa1111/rss/on_prima.jpg" enc:type="image/jpeg"/>
<dc:title>New space telescope will reopen astronomers' view of the far-infrared</dc:title>
<dc:identifier>doi:10.1126/science.aaaa1111</dc:identifier>
<dc:date>2026-09-25T04:30:00Z</dc:date>
<dc:creator>Daniel Clery</dc:creator>
</item>
<item rdf:about="https://www.science.org/doi/10.1126/science.bbbb2222">
<title>Japan's Science Council to face greater governmental oversight</title>
<link>https://www.science.org/content/article/japan-science-council-oversight</link>
<description>Imminent change in legal status raises concerns.</description>
<enc:enclosure rdf:resource="https://www.science.org/do/10.1126/science.bbbb2222/rss/on_japan.jpg" enc:type="image/jpeg"/>
<dc:title>Japan's Science Council to face greater governmental oversight</dc:title>
<dc:date>2026-09-25T05:18:00Z</dc:date>
<dc:creator>Dennis Normile</dc:creator>
</item>
<item rdf:about="https://www.science.org/doi/10.1126/science.cccc3333">
<title>Oldest item by publish time</title>
<link>https://www.science.org/content/article/oldest-item</link>
<description>Published earlier than the other two.</description>
<dc:date>2026-09-24T09:00:00Z</dc:date>
<dc:creator>Meredith Wadman</dc:creator>
</item>
</rdf:RDF>
"""


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/science-news/hot",
        "query_string": b"",
        "headers": [],
    })


def _mock(monkeypatch, body: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake_get(**kwargs):
        seen.update(kwargs)
        return RequestResult(False, _UPDATE_TIME, body)

    monkeypatch.setattr(science_news, "get", fake_get)
    return seen


async def test_items_keep_feed_document_order(monkeypatch):
    seen = _mock(monkeypatch, _RDF_FEED)
    result = await science_news.handle_route(_request(), no_cache=True)

    assert seen["url"] == "https://www.science.org/rss/news_current.xml"
    assert result.name == "science-news"
    assert result.title == "Science 杂志"
    assert result.type == "Latest News"
    assert result.total == 3
    # 文档顺序 A(04:30) → B(05:18) → C(昨天):不按时间重排(重排会变成 B → A → C)
    assert [item.title.split()[0] for item in result.data] == [
        "New",
        "Japan's",
        "Oldest",
    ]


async def test_item_fields_map_from_rdf(monkeypatch):
    _mock(monkeypatch, _RDF_FEED)
    result = await science_news.handle_route(_request(), no_cache=True)

    first, second = result.data[0], result.data[1]
    assert first.id == first.url == first.mobileUrl == \
        "https://www.science.org/content/article/new-space-telescope-far-infrared"  # 无 guid,链接即 id
    assert first.title == "New space telescope will reopen astronomers' view of the far-infrared"
    assert first.author == "Daniel Clery"  # dc:creator
    assert first.desc == "NASA's $1.2 billion PRIMA will explore how galaxies evolve."
    assert first.cover is None  # enc:enclosure 图不带会话 cookie 一律 403,不补
    assert first.hot is None
    assert first.timestamp == int(datetime(2026, 9, 25, 4, 30, tzinfo=UTC).timestamp() * 1000)  # dc:date → 毫秒
    assert second.timestamp == int(datetime(2026, 9, 25, 5, 18, tzinfo=UTC).timestamp() * 1000)


async def test_non_feed_response_is_an_error(monkeypatch):
    _mock(monkeypatch, "<html>This page is protected by Cloudflare challenge</html>")
    with pytest.raises(RuntimeError, match="did not return any"):
        await science_news.handle_route(_request(), no_cache=True)


async def test_empty_items_are_an_error(monkeypatch):
    # 有 item 但没有可用的链接 → 解析结果为空,路由层报错(不静默降级为空榜)
    _mock(monkeypatch, (
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns="http://purl.org/rss/1.0/"><channel/>'
        "<item><title>No link item</title></item></rdf:RDF>"
    ))
    with pytest.raises(RuntimeError, match="returned no items"):
        await science_news.handle_route(_request(), no_cache=True)


async def test_cached_result_propagates_from_cache(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(True, _UPDATE_TIME, _RDF_FEED)

    monkeypatch.setattr(science_news, "get", fake_get)
    result = await science_news.handle_route(_request(), no_cache=False)

    assert result.fromCache is True
    assert result.updateTime == _UPDATE_TIME
    assert result.total == 3
