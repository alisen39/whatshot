from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.routes.newsflash import coindesk_news
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:media="http://search.yahoo.com/mrss/" version="2.0">
  <channel>
    <title>CoinDesk</title>
    <item>
      <title>Older crypto story</title>
      <link>https://www.coindesk.com/markets/2026/08/25/older</link>
      <media:content url="https://cdn.example.com/older.jpg" type="image/*" medium="image" />
      <guid isPermaLink="false">article-older</guid>
      <pubDate>Tue, 25 Aug 2026 12:00:00 +0000</pubDate>
      <description><![CDATA[<p>Older story summary.</p>]]></description>
      <dc:creator>Older Author</dc:creator>
      <content:encoded><![CDATA[]]></content:encoded>
      <category>Markets</category>
    </item>
    <item>
      <title>Latest crypto story</title>
      <link>https://www.coindesk.com/business/2026/08/25/latest</link>
      <media:content url="https://cdn.example.com/latest.jpg" type="image/*" medium="image" />
      <guid isPermaLink="false">article-latest</guid>
      <pubDate>Tue, 25 Aug 2026 16:22:47 +0000</pubDate>
      <description><![CDATA[<p>Latest <strong>story</strong> summary.</p>]]></description>
      <dc:creator>Latest Author</dc:creator>
      <content:encoded><![CDATA[]]></content:encoded>
      <category>Finance</category>
      <category>Tokenization</category>
      <category>Finance</category>
    </item>
  </channel>
</rss>
"""


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/coindesk-news",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_coindesk_uses_official_rss_and_maps_newsflash_fields(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-25T16:30:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(coindesk_news, "get", fake_get)
    result = await coindesk_news.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": coindesk_news.FEED_URL,
        "no_cache": True,
        "ttl": config.NEWSFLASH_CACHE_TTL,
        "response_type": "text",
    }
    assert result.kind == "newsflash"
    assert result.type == "加密货币新闻"
    assert result.updateTime == "2026-08-25T16:30:00+00:00"
    assert result.total == 2

    item = result.data[0]
    assert item.id == "article-latest"
    assert item.title == "Latest crypto story"
    assert item.content == "Latest story summary."
    assert item.summary == "Latest story summary."
    assert item.contentStatus == "summary"
    assert item.source == "Latest Author"
    assert item.tags == ["Finance", "Tokenization"]
    assert item.images == ["https://cdn.example.com/latest.jpg"]
    assert item.timestamp == 1787674967000
    assert item.url == "https://www.coindesk.com/business/2026/08/25/latest"


@pytest.mark.asyncio
async def test_coindesk_rejects_html_error_page(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-08-25T16:30:00+00:00", "<html>blocked</html>")

    monkeypatch.setattr(coindesk_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="non-empty RSS feed"):
        await coindesk_news.handle_route(_request(), no_cache=True)
