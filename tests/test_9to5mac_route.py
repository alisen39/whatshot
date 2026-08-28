from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nine_to_five_mac
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_9to5mac_parses_official_rss(monkeypatch):
    rss = (
        '<rss version="2.0"><channel><title>9to5Mac</title>'
        '<item><guid>https://9to5mac.com/?p=123</guid><link>https://9to5mac.com/2026/08/28/test-post/</link>'
        '<title>Test post</title><pubDate>Fri, 28 Aug 2026 10:00:00 +0000</pubDate></item>'
        '</channel></rss>'
    )

    async def fake_get(*args, **kwargs):
        assert kwargs["url"] == "https://9to5mac.com/feed/"
        return RequestResult(False, "2026-08-28T00:00:00+00:00", rss)

    monkeypatch.setattr(nine_to_five_mac, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/9to5mac", "query_string": b"", "headers": []})
    result = await nine_to_five_mac.handle_route(request, no_cache=True)

    assert result.name == "9to5mac"
    assert result.total == 1
    assert result.data[0].url == "https://9to5mac.com/2026/08/28/test-post/"


@pytest.mark.asyncio
async def test_9to5mac_fails_explicitly_on_empty_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-28T00:00:00+00:00", "<rss version=\"2.0\"><channel/></rss>")

    monkeypatch.setattr(nine_to_five_mac, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/9to5mac", "query_string": b"", "headers": []})
    with pytest.raises(RuntimeError, match="no usable items"):
        await nine_to_five_mac.handle_route(request, no_cache=True)
