from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.models import NewsFlashItem
from whats_hot_api.routes.newsflash import anthropic_research
from whats_hot_api.utils.http_client import RequestResult

HTML = """
<html><body>
  <section>
    <a href="/research/featured"><time>Aug 30, 2026</time><h4>Featured noise</h4></a>
  </section>
  <ul>
    <li>
      <a href="/research/newest">
        <div><time>Aug 26, 2026</time><span>Societal Impacts</span></div>
        <span>Newest research</span>
      </a>
    </li>
    <li>
      <a href="/research/older?tracking=1">
        <div><time>Jul 9, 2026</time><span>Frontier Red Team</span></div>
        <span>Older research</span>
      </a>
    </li>
    <li>
      <a href="https://example.com/research/external">
        <time>Aug 20, 2026</time><span>Other</span><span>External</span>
      </a>
    </li>
  </ul>
</body></html>
"""


def _request(query_string: bytes = b"type=research") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/anthropic-research/research",
            "query_string": query_string,
            "headers": [],
        }
    )


def test_parse_page_maps_visible_publication_rows() -> None:
    items = anthropic_research._parse_page(HTML)

    assert items == [
        NewsFlashItem(
            id="/research/newest",
            title="Newest research",
            content="Newest research",
            summary="Newest research",
            contentStatus="summary",
            source="Anthropic",
            tags=["Societal Impacts"],
            timestamp=int(datetime(2026, 8, 26, tzinfo=UTC).timestamp() * 1000),
            url="https://www.anthropic.com/research/newest",
            mobileUrl="https://www.anthropic.com/research/newest",
        ),
        NewsFlashItem(
            id="/research/older",
            title="Older research",
            content="Older research",
            summary="Older research",
            contentStatus="summary",
            source="Anthropic",
            tags=["Frontier Red Team"],
            timestamp=int(datetime(2026, 7, 9, tzinfo=UTC).timestamp() * 1000),
            url="https://www.anthropic.com/research/older",
            mobileUrl="https://www.anthropic.com/research/older",
        ),
    ]


def test_parse_page_rejects_empty_or_changed_publication_list() -> None:
    with pytest.raises(RuntimeError, match="no publication rows"):
        anthropic_research._parse_page("<html><body><h1>Research</h1></body></html>")


async def test_route_fetches_official_page_as_newsflash(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs == {
            "url": anthropic_research.SOURCE_LINK,
            "no_cache": True,
            "ttl": anthropic_research.config.NEWSFLASH_CACHE_TTL,
            "response_type": "text",
        }
        return RequestResult(False, "2026-08-27T00:00:00+00:00", HTML)

    monkeypatch.setattr(anthropic_research, "get", fake_get)

    result = await anthropic_research.handle_route(_request(), no_cache=True)

    assert result.kind == "newsflash"
    assert result.type == "Research"
    assert result.total == 2
    assert result.fromCache is False


def test_route_declares_only_grouped_research_type() -> None:
    assert anthropic_research.ROUTE_META["params"]["type"]["type"] == {
        "research": "Research"
    }
