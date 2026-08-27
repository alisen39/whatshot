from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import indiehackers
from whats_hot_api.utils.http_client import RequestResult

RSS = (
    '<rss version="2.0"><channel><title>Indie Hackers</title>'
    '<item><guid>https://indiehackers.com/post/1</guid><link>https://www.indiehackers.com/post/1</link>'
    '<title>Making $10k MRR</title><pubDate>Fri, 28 Aug 2026 10:00:00 +0000</pubDate></item>'
    '</channel></rss>'
)


@pytest.mark.asyncio
async def test_indiehackers_parses_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        assert kwargs["url"].startswith("https://news.google.com/rss/search?q=site%3Aindiehackers.com")
        return RequestResult(False, "2026-08-28T00:00:00+00:00", RSS)

    monkeypatch.setattr(indiehackers, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/indiehackers", "query_string": b"", "headers": []})
    result = await indiehackers.handle_route(request, no_cache=True)

    assert result.name == "indiehackers"
    assert result.total == 1
    assert result.data[0].url == "https://www.indiehackers.com/post/1"


@pytest.mark.asyncio
async def test_indiehackers_fails_explicitly_on_empty_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-28T00:00:00+00:00", '<rss version="2.0"><channel/></rss>')

    monkeypatch.setattr(indiehackers, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/indiehackers", "query_string": b"", "headers": []})
    with pytest.raises(RuntimeError, match="no usable items"):
        await indiehackers.handle_route(request, no_cache=True)
