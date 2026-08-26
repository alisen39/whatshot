from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.routes.newsflash import qbitai_embodied
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>具身智能 – 量子位</title>
    <item>
      <title>Older embodied-AI story</title>
      <link>https://www.qbitai.com/2026/08/older.html</link>
      <guid>https://www.qbitai.com/?p=100</guid>
      <pubDate>Tue, 11 Aug 2026 03:37:31 +0000</pubDate>
      <description></description>
      <dc:creator>林, 方舟</dc:creator>
      <category>资讯</category>
      <category>具身智能</category>
    </item>
    <item>
      <title>Latest embodied-AI story</title>
      <link>https://www.qbitai.com/2026/08/latest.html</link>
      <guid>https://www.qbitai.com/?p=101</guid>
      <pubDate>Tue, 11 Aug 2026 04:42:50 +0000</pubDate>
      <description><![CDATA[<p>Latest <strong>story</strong> summary.</p>]]></description>
      <dc:creator>henry</dc:creator>
      <category>资讯</category>
      <category>具身智能</category>
      <category>资讯</category>
    </item>
  </channel>
</rss>
"""


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/qbitai-embodied",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_qbitai_uses_official_tag_rss_and_maps_newsflash_fields(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T01:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(qbitai_embodied, "get", fake_get)
    result = await qbitai_embodied.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": qbitai_embodied.FEED_URL,
        "no_cache": True,
        "ttl": config.NEWSFLASH_CACHE_TTL,
        "response_type": "text",
        "headers": {"User-Agent": "WhatsHot/1.0"},
    }
    assert result.kind == "newsflash"
    assert result.type == "量子位资讯"
    assert result.updateTime == "2026-08-27T01:00:00+00:00"
    assert result.total == 2

    latest = result.data[0]
    assert latest.id == "https://www.qbitai.com/?p=101"
    assert latest.title == "Latest embodied-AI story"
    assert latest.content == "Latest story summary."
    assert latest.summary == "Latest story summary."
    assert latest.contentStatus == "summary"
    assert latest.source == "henry"
    assert latest.tags == ["资讯", "具身智能"]
    assert latest.timestamp == 1786423370000
    assert latest.url == "https://www.qbitai.com/2026/08/latest.html"

    older = result.data[1]
    assert older.content == older.title
    assert older.summary is None
    assert older.source == "林, 方舟"


@pytest.mark.asyncio
async def test_qbitai_rejects_html_error_page(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-08-27T01:00:00+00:00", "<html>blocked</html>")

    monkeypatch.setattr(qbitai_embodied, "get", fake_get)
    with pytest.raises(RuntimeError, match="non-empty RSS feed"):
        await qbitai_embodied.handle_route(_request(), no_cache=True)


def test_qbitai_rejects_feed_without_usable_articles():
    xml = """<rss><channel><item><title>Missing link</title></item></channel></rss>"""

    with pytest.raises(RuntimeError, match="no usable articles"):
        qbitai_embodied._parse_feed(xml)
