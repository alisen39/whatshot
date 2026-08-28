from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import phys_org
from whats_hot_api.utils.http_client import RequestResult

HOUSE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
)
SAMPLE_RSS = (
    '<rss version="2.0"><channel><title>Phys.org</title>'
    '<item><title>Robots learn to fold</title>'
    '<link>https://phys.org/news/physics-find.html</link></item>'
    '</channel></rss>'
)


@pytest.mark.asyncio
async def test_phys_org_request_carries_verified_browser_user_agent(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T00:00:00+00:00", SAMPLE_RSS)

    monkeypatch.setattr(phys_org, "get", fake_get)
    data = await phys_org._get_list(no_cache=True)

    assert captured["headers"]["User-Agent"] == HOUSE_UA
    assert captured["no_cache"] is True
    assert data["from_cache"] is False
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_phys_org_route_returns_parsed_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-27T00:00:00+00:00", SAMPLE_RSS)

    monkeypatch.setattr(phys_org, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/phys-org",
        "query_string": b"",
        "headers": [],
    })
    result = await phys_org.handle_route(request, no_cache=True)

    assert result.name == "phys-org"
    assert result.total == 1
    assert result.data[0].url == "https://phys.org/news/physics-find.html"
