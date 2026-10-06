from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bbc_sport
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = (
    "<?xml version=\"1.0\"?><rss xmlns:media=\"http://search.yahoo.com/mrss/\"><channel>"
    "<item><guid>https://www.bbc.co.uk/sport/football/articles/abc#0</guid>"
    "<title>Sport story</title>"
    "<link>https://www.bbc.co.uk/sport/football/articles/abc</link>"
    "<media:thumbnail url=\"https://ichef.bbci.co.uk/240x135/1.jpg\"/></item>"
    "</channel></rss>"
)


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/bbc-sport",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_sport_feed_is_parsed(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(bbc_sport, "get", fake_get)
    result = await bbc_sport.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://feeds.bbci.co.uk/sport/rss.xml"
    assert result.name == "bbc-sport"
    assert result.type == "体育"
    assert result.total == 1
    item = result.data[0]
    assert item.title == "Sport story"
    assert item.url == "https://www.bbc.co.uk/sport/football/articles/abc"
    assert item.cover == "https://ichef.bbci.co.uk/240x135/1.jpg"


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>blocked</html>")

    monkeypatch.setattr(bbc_sport, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await bbc_sport.handle_route(_request(), no_cache=True)
