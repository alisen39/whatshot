from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import medium
from whats_hot_api.utils.http_client import RequestResult

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
  <item>
    <title><![CDATA[Technology article A]]></title>
    <description><![CDATA[<p>First <strong>summary</strong>.</p>]]></description>
    <link>https://medium.com/@writer/article-a-55009c06ba15?source=rss</link>
    <guid isPermaLink="false">https://medium.com/p/55009c06ba15</guid>
    <dc:creator><![CDATA[Writer A]]></dc:creator>
    <pubDate>Sun, 19 Jul 2026 01:19:38 GMT</pubDate>
  </item>
  <item>
    <title>Duplicate should be ignored</title>
    <guid>https://medium.com/p/55009c06ba15</guid>
  </item>
  <item>
    <title>Invalid identity should be ignored</title>
    <guid>https://medium.com/@writer/not-stable</guid>
  </item>
  <item>
    <title>Technology article B</title>
    <guid>https://medium.com/p/3b03bbe29ef6</guid>
    <pubDate>Sun, 19 Jul 2026 01:15:00 GMT</pubDate>
  </item>
</channel></rss>"""


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_parser_uses_medium_guids_as_stable_article_identity() -> None:
    rows = medium._parse_feed(FEED)

    assert [row.id for row in rows] == ["55009c06ba15", "3b03bbe29ef6"]
    assert rows[0].url == "https://medium.com/p/55009c06ba15"
    assert rows[0].mobileUrl == rows[0].url
    assert rows[0].author == "Writer A"
    assert rows[0].desc == "First summary ."
    assert rows[0].timestamp == 1784423978000


@pytest.mark.asyncio
async def test_route_uses_fixed_public_technology_rss(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs["url"] == medium.FEED_URL
        return RequestResult(False, "2026-07-19T01:20:00Z", FEED)

    monkeypatch.setattr(medium, "get", fake_get)
    result = await medium.handle_route(_request())

    assert result.name == "medium"
    assert result.type == "Technology"
    assert result.total == 2
