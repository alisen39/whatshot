from __future__ import annotations

import pytest

from whats_hot_api.routes.hotlist import techxplore_robotics
from whats_hot_api.utils.http_client import RequestResult

HOUSE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
)
SAMPLE_RSS = (
    '<rss version="2.0"><channel><title>Tech Xplore</title>'
    '<item><title>Robots learn to fold</title>'
    '<link>https://techxplore.com/news/robotics-folding.html</link></item>'
    '</channel></rss>'
)


@pytest.mark.asyncio
async def test_techxplore_request_carries_verified_browser_user_agent(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T00:00:00+00:00", SAMPLE_RSS)

    monkeypatch.setattr(techxplore_robotics, "get", fake_get)
    data = await techxplore_robotics._get_list(no_cache=True)

    assert captured["headers"]["User-Agent"] == HOUSE_UA
    assert captured["no_cache"] is True
    assert data["from_cache"] is False
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_techxplore_route_returns_parsed_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-27T00:00:00+00:00", SAMPLE_RSS)

    monkeypatch.setattr(techxplore_robotics, "get", fake_get)
    from starlette.requests import Request

    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/techxplore-robotics",
        "query_string": b"",
        "headers": [],
    })
    result = await techxplore_robotics.handle_route(request, no_cache=True)

    assert result.name == "techxplore-robotics"
    assert result.total == 1
    assert result.data[0].url == "https://techxplore.com/news/robotics-folding.html"
