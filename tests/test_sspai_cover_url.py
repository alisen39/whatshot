"""少数派 banner paths must use the upstream image CDN."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import sspai
from whats_hot_api.utils.http_client import RequestResult
from whats_hot_api.utils.sspai import sspai_cover_url


@pytest.mark.parametrize(
    ("banner", "expected"),
    [
        ("2026/6/1/article/example.png", "https://rssfile.sspai.com/2026/6/1/article/example.png"),
        ("/2026/05/17/example.png", "https://rssfile.sspai.com/2026/05/17/example.png"),
        ("26/06/2025/article/6adad18f-4728-2779-1d22-4eca3468416b.jpeg", "https://rssfile.sspai.com/26/06/2025/article/6adad18f-4728-2779-1d22-4eca3468416b.jpeg"),
        ("https://cdnfile.sspai.com/2026/10/25/test.jfif?size=small", "https://rssfile.sspai.com/2026/10/25/test.jfif?size=small"),
        ("http://cdnfile.sspai.com/26/06/2025/article/example.jpeg", "https://rssfile.sspai.com/26/06/2025/article/example.jpeg"),
        ("https://cdnfile.sspai.com/ui/logo.png", "https://cdnfile.sspai.com/ui/logo.png"),
        ("https://cdnfile.sspai.com.evil/2026/10/25/test.jfif", "https://cdnfile.sspai.com.evil/2026/10/25/test.jfif"),
        ("https://cdn-static.sspai.com/example.png", "https://cdn-static.sspai.com/example.png"),
        ("", None),
        (None, None),
    ],
)
def test_sspai_cover_url(banner, expected):
    assert sspai_cover_url(banner) == expected


@pytest.mark.asyncio
async def test_sspai_route_resolves_upstream_banner(monkeypatch):
    async def fake_get(*, url, no_cache):
        assert url == "https://sspai.com/api/v1/article/tag/page/get?limit=40&tag=热门文章"
        assert no_cache is True
        return RequestResult(False, "2026-10-27T16:32:19+00:00", {"data": [
            {"id": 117633, "title": "社区速递", "banner": "2026/6/30/article/example.png"},
        ]})

    monkeypatch.setattr(sspai, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/sspai", "query_string": b"", "headers": []})
    result = await sspai.handle_route(request, no_cache=True)

    assert result.data[0].url == "https://sspai.com/post/117633"
    assert result.data[0].cover == "https://rssfile.sspai.com/2026/6/30/article/example.png"
