from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import (
    ars_technica,
    freecodecamp,
    lwn,
    phoronix,
    slashdot,
)
from whats_hot_api.utils.http_client import RequestResult

ROUTES = (slashdot, lwn, phoronix, ars_technica, freecodecamp)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Older article</title>
    <link>https://example.com/older</link>
    <guid>older</guid>
    <description><![CDATA[<p>Older summary</p>]]></description>
    <pubDate>Tue, 28 Jul 2026 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Newest article</title>
    <link>https://example.com/newest</link>
    <guid>newest</guid>
    <description><![CDATA[<p>Newest summary</p><img src="https://example.com/cover.png"/>]]></description>
    <author>WhatsHot Author</author>
    <pubDate>Wed, 29 Jul 2026 10:00:00 +0000</pubDate>
  </item>
</channel></rss>
"""


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ROUTES, ids=lambda module: module.ROUTE_NAME)
async def test_native_rss_route_owns_request_and_metadata(monkeypatch, module):
    captured: dict[str, object] = {}

    async def fake_get(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return RequestResult(False, "2026-07-30T00:00:00+00:00", RSS)

    monkeypatch.setattr(module, "get", fake_get)
    result = await module.handle_route(_request(), no_cache=True)

    assert captured["url"] == module.FEED_URL
    assert captured["no_cache"] is True
    assert captured["response_type"] == "text"
    assert captured["headers"]["Referer"] == module.SOURCE_LINK
    assert result.name == module.ROUTE_NAME
    assert result.title == module.ROUTE_META["title"]
    assert result.type == "RSS"
    assert result.fromCache is False
    assert result.updateTime == "2026-07-30T00:00:00+00:00"
    assert [item.id for item in result.data] == ["newest", "older"]
    assert result.data[0].author == "WhatsHot Author"
    assert result.data[0].desc == "Newest summary"
    assert result.data[0].cover == "https://example.com/cover.png"
