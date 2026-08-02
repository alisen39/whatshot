from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import qwen
from whats_hot_api.utils.http_client import RequestResult


LEGACY_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Qwen3Guard</title>
    <link>https://qwenlm.github.io/blog/qwen3guard/</link>
    <guid>https://qwenlm.github.io/blog/qwen3guard/</guid>
    <description><![CDATA[<p>Real-time safety for token streams.</p>]]></description>
    <pubDate>Tue, 23 Sep 2025 04:00:00 +0800</pubDate>
  </item>
  <item>
    <title>Qwen Image</title>
    <link>https://qwenlm.github.io/blog/qwen-image/</link>
    <description>Native text rendering.</description>
    <pubDate>Mon, 04 Aug 2025 22:08:30 +0800</pubDate>
  </item>
</channel></rss>
"""


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/qwen/research",
        "query_string": query,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_qwen_reuses_current_official_research_board(monkeypatch):
    async def fake_research(no_cache):  # noqa: ANN001
        assert no_cache is True
        return {
            "from_cache": False,
            "update_time": "2026-07-17T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(qwen.qwen_research, "_get_list", fake_research)
    route_data = await qwen.handle_route(_request(), no_cache=True)

    assert route_data.name == "qwen"
    assert route_data.type == "研究与发布"
    assert route_data.data == []


@pytest.mark.asyncio
async def test_qwen_fetches_official_legacy_blog_rss(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://qwenlm.github.io/blog/index.xml"
        assert kwargs["cache_key"] == "qwen:legacy-blog:latest:50"
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            LEGACY_RSS,
        )

    monkeypatch.setattr(qwen, "get", fake_get)
    route_data = await qwen.handle_route(_request(b"type=legacy-blog"))

    assert route_data.type == "历史博客"
    assert [item.id for item in route_data.data] == ["qwen3guard", "qwen-image"]
    first = route_data.data[0]
    assert first.author == "Qwen Team"
    assert first.desc == "Real-time safety for token streams."
    assert first.timestamp == 1758571200000
    assert first.url == "https://qwenlm.github.io/blog/qwen3guard/"


def test_qwen_legacy_parser_rejects_foreign_urls_and_duplicate_slugs():
    duplicate = LEGACY_RSS.replace(
        "</channel>",
        """
        <item>
          <title>Duplicate</title>
          <link>https://qwenlm.github.io/blog/qwen3guard/</link>
          <pubDate>Wed, 24 Sep 2025 04:00:00 +0800</pubDate>
        </item>
        <item>
          <title>Foreign</title>
          <link>https://example.com/blog/foreign/</link>
          <pubDate>Wed, 24 Sep 2025 04:00:00 +0800</pubDate>
        </item>
        </channel>
        """,
    )

    items = qwen._parse_legacy_blog(duplicate)

    assert [item.id for item in items].count("qwen3guard") == 1
    assert all(item.id != "foreign" for item in items)
