from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import reuters


def _request(query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/reuters/default",
            "query_string": query.encode(),
            "headers": [],
        }
    )


def test_reuters_declares_official_and_google_news_boards() -> None:
    assert reuters.ROUTE_META["params"]["type"]["type"] == {
        "official": "官方最新",
        "google-news": "Google News 聚合",
    }


def test_parse_official_sitemap_filters_locales_deduplicates_and_sorts() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
      xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
      xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url>
        <loc>https://www.reuters.com/world/europe/older-story-2026-07-17/</loc>
        <news:news><news:publication_date>2026-07-17T10:00:00Z</news:publication_date><news:title>Older story</news:title></news:news>
      </url>
      <url>
        <loc>https://www.reuters.com/technology/newer-story-2026-07-17/</loc>
        <news:news><news:publication_date>2026-07-17T11:00:00.500Z</news:publication_date><news:title>Newer story</news:title></news:news>
        <image:image><image:loc>https://cloudfront-us-east-2.images.arcpublishing.com/reuters/example.jpg</image:loc></image:image>
      </url>
      <url>
        <loc>https://www.reuters.com/technology/newer-story-2026-07-17/</loc>
        <news:news><news:publication_date>2026-07-17T11:00:00.500Z</news:publication_date><news:title>Duplicate</news:title></news:news>
      </url>
      <url>
        <loc>https://www.reuters.com/fr/affaires/histoire-2026-07-17/</loc>
        <news:news><news:publication_date>2026-07-17T12:00:00Z</news:publication_date><news:title>French story</news:title></news:news>
      </url>
      <url>
        <loc>https://example.com/world/not-reuters/</loc>
        <news:news><news:publication_date>2026-07-17T13:00:00Z</news:publication_date><news:title>Wrong host</news:title></news:news>
      </url>
    </urlset>"""

    rows = reuters._parse_official_news_sitemap(xml)

    assert [row.title for row in rows] == ["Newer story", "Older story"]
    assert rows[0].id == "technology/newer-story-2026-07-17"
    assert rows[0].timestamp == 1784286000500
    assert rows[0].author == "Reuters"
    assert rows[0].desc == "栏目：technology"
    assert rows[0].cover and rows[0].cover.endswith("example.jpg")
    assert rows[0].url == rows[0].mobileUrl


@pytest.mark.asyncio
async def test_google_news_board_uses_owned_feed(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == reuters._GOOGLE_NEWS_URL
        assert kwargs["no_cache"] is True
        from whats_hot_api.utils.http_client import RequestResult
        return RequestResult(False, datetime(2026, 7, 17, tzinfo=UTC).isoformat(), "<rss><channel><item><guid>google-id</guid><title>Reuters report</title><link>https://news.google.com/rss/articles/google-id</link></item></channel></rss>")

    monkeypatch.setattr(reuters, "get", fake_get)
    result = await reuters.handle_route(_request("type=google-news"), True)

    assert result.type == "Google News 聚合"
    assert result.total == 1


@pytest.mark.asyncio
async def test_default_compatibility_path_selects_official_board(monkeypatch) -> None:
    async def fake_official(no_cache):
        assert no_cache is False
        return {
            "from_cache": True,
            "update_time": datetime(2026, 7, 17, tzinfo=UTC).isoformat(),
            "data": [],
        }

    monkeypatch.setattr(reuters, "_get_official", fake_official)
    result = await reuters.handle_route(_request("type=default"))

    assert result.type == "官方最新"
    assert result.fromCache is True
