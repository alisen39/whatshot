from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import neuroscience_news
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Earlier brain story - Neuroscience News</title>
      <link>https://news.google.com/rss/articles/earlier?oc=5</link>
      <guid isPermaLink="false">earlier-guid</guid>
      <pubDate>Fri, 28 Aug 2026 09:00:00 GMT</pubDate>
      <description><![CDATA[<a href="https://news.google.com/rss/articles/earlier?oc=5">Earlier brain story</a>]]></description>
      <source url="https://neurosciencenews.com">Neuroscience News</source>
    </item>
    <item>
      <title>Latest brain story - Neuroscience News</title>
      <link>https://news.google.com/rss/articles/latest?oc=5</link>
      <guid isPermaLink="false">latest-guid</guid>
      <pubDate>Sat, 29 Aug 2026 10:30:00 GMT</pubDate>
      <description><![CDATA[<a href="https://news.google.com/rss/articles/latest?oc=5">Latest brain story</a>]]></description>
      <source url="https://neurosciencenews.com">Neuroscience News</source>
    </item>
  </channel>
</rss>
"""


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/neuroscience-news",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_neuroscience_news_uses_site_feed_and_maps_items(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-29T18:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(neuroscience_news, "get", fake_get)
    result = await neuroscience_news.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": "https://news.google.com/rss/search?q=site%3Aneurosciencenews.com",
        "no_cache": True,
        "response_type": "text",
    }
    assert result.total == 2
    assert result.updateTime == "2026-08-29T18:00:00+00:00"
    assert result.data[0].id == "latest-guid"
    assert result.data[0].title == "Latest brain story - Neuroscience News"
    assert result.data[0].author == "Neuroscience News"
    assert result.data[0].url == "https://news.google.com/rss/articles/latest?oc=5"
    assert result.data[0].timestamp == 1787999400000


@pytest.mark.asyncio
async def test_neuroscience_news_rejects_empty_feed(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-08-29T18:00:00+00:00", "<rss><channel /></rss>")

    monkeypatch.setattr(neuroscience_news, "get", fake_get)

    with pytest.raises(RuntimeError, match="non-empty RSS feed"):
        await neuroscience_news.handle_route(_request(), no_cache=True)
