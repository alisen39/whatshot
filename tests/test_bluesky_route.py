from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bluesky
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_bluesky_trending_topics(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {
            "topics": [{"topic": "World Cup", "link": "/profile/trending.bsky.app/feed/123"}]
        })

    monkeypatch.setattr(bluesky, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/bluesky", "query_string": b"", "headers": []})
    route_data = await bluesky.handle_route(request)

    assert route_data.total == 1
    assert route_data.data[0].id == "/profile/trending.bsky.app/feed/123"
    assert route_data.data[0].url == "https://bsky.app/profile/trending.bsky.app/feed/123"


@pytest.mark.asyncio
async def test_bluesky_popular_feeds_use_stable_at_uri(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == bluesky._POPULAR_FEEDS_URL
        assert kwargs["params"] == {"limit": "50"}
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {
            "feeds": [{
                "uri": "at://did:plc:3guzzweuqraryl3rdkimjamk/app.bsky.feed.generator/for-you",
                "displayName": "For You",
                "description": "A public feed",
                "likeCount": 51513,
                "creator": {"handle": "spacecowboy17.bsky.social"},
            }]
        })

    monkeypatch.setattr(bluesky, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/bluesky", "query_string": b"type=popular-feeds", "headers": []})
    route_data = await bluesky.handle_route(request)

    assert route_data.type == "热门信息流"
    assert route_data.data[0].id.startswith("at://did:plc:")
    assert route_data.data[0].url == "https://bsky.app/profile/did:plc:3guzzweuqraryl3rdkimjamk/feed/for-you"
    assert "点赞：51,513" in route_data.data[0].desc
