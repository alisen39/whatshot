from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import google_trends
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_google_trends_extracts_region_feed(monkeypatch):
    xml = """
    <rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>
      <title>ps6</title>
      <ht:approx_traffic>2,000+</ht:approx_traffic>
      <pubDate>Wed, 15 Jul 2026 11:50:00 -0700</pubDate>
      <ht:picture>https://example.com/picture.jpg</ht:picture>
      <ht:picture_source>The Verge</ht:picture_source>
      <ht:news_item><ht:news_item_title>The PS6 sure sounds like a handheld</ht:news_item_title></ht:news_item>
    </item></channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://trends.google.com/trending/rss"
        assert kwargs["params"] == {"geo": "US"}
        return RequestResult(False, "2026-07-16T00:00:00+00:00", xml)

    monkeypatch.setattr(google_trends, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/google-trends", "query_string": b"type=US", "headers": []}
    )
    route_data = await google_trends.handle_route(request)

    assert route_data.type == "美国每日趋势"
    item = route_data.data[0]
    assert item.id == "US:Wed, 15 Jul 2026 11:50:00 -0700:ps6"
    assert item.hot == 2000
    assert item.author == "The Verge"
    assert item.desc == "The PS6 sure sounds like a handheld"
    assert item.url == "https://trends.google.com/trends/explore?geo=US&q=ps6"


def test_google_trends_traffic_number():
    assert google_trends._traffic_number("1,000,000+") == 1000000
    assert google_trends._traffic_number("") is None
