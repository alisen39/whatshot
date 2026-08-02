from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import rfc
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/rfc/hot",
            "query_string": b"",
            "headers": [],
        }
    )


def test_parse_recent_rfc_feed_validates_identity_deduplicates_and_sorts() -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>RFC 9000: QUIC: A UDP-Based Multiplexed and Secure Transport</title>
        <link>https://www.rfc-editor.org/info/rfc9000/</link>
        <guid>https://www.rfc-editor.org/info/rfc9000/</guid>
        <pubDate>Thu, 27 May 2021 00:00:00 GMT</pubDate>
        <description><![CDATA[<p>This document defines <b>QUIC</b>.</p>]]></description>
      </item>
      <item>
        <title>RFC 9114: HTTP/3</title>
        <link>https://www.rfc-editor.org/info/rfc9114/</link>
        <pubDate>Mon, 06 Jun 2022 00:00:00 GMT</pubDate>
        <description>HTTP semantics over QUIC.</description>
      </item>
      <item>
        <title>RFC 9114: Duplicate</title>
        <link>https://www.rfc-editor.org/info/rfc9114/</link>
        <pubDate>Mon, 06 Jun 2022 00:00:00 GMT</pubDate>
      </item>
      <item>
        <title>RFC 9999: Mismatched number</title>
        <link>https://www.rfc-editor.org/info/rfc9998/</link>
        <pubDate>Tue, 07 Jun 2022 00:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Not an RFC</title>
        <link>https://example.com/</link>
        <pubDate>Wed, 08 Jun 2022 00:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    rows = rfc._parse_feed(xml)

    assert [row.id for row in rows] == ["rfc9114", "rfc9000"]
    assert rows[0].title == "RFC 9114: HTTP/3"
    assert rows[0].author == "RFC Editor"
    assert rows[0].url == rows[0].mobileUrl
    assert rows[1].desc == "This document defines QUIC ."


@pytest.mark.asyncio
async def test_rfc_route_returns_recent_publications(monkeypatch) -> None:
    xml = """<rss version="2.0"><channel><item>
      <title>RFC 10015: Deprecating Obsolete Key Exchange Methods</title>
      <link>https://www.rfc-editor.org/info/rfc10015/</link>
      <pubDate>Thu, 16 Jul 2026 00:00:00 GMT</pubDate>
      <description>Deprecates obsolete methods.</description>
    </item></channel></rss>"""

    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.rfc-editor.org/rfcrss.xml"
        return RequestResult(
            data=xml,
            from_cache=False,
            update_time=datetime(2026, 7, 17, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(rfc, "get", fake_get)
    result = await rfc.handle_route(_request(), True)

    assert result.name == "rfc"
    assert result.type == "最近发布"
    assert result.total == 1
    assert result.data[0].id == "rfc10015"
