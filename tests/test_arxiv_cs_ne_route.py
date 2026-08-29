from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import arxiv_cs_ne
from whats_hot_api.utils.http_client import RequestResult

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2608.27150v1</id>
    <updated>2026-08-29T10:30:00Z</updated>
    <published>2026-08-29T10:30:00Z</published>
    <title>Newest neural computing paper</title>
    <summary>A compact abstract.</summary>
    <author><name>Ada Researcher</name></author>
    <link href="https://arxiv.org/abs/2608.27150v1" rel="alternate" type="text/html" />
  </entry>
</feed>
"""


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=arxiv_cs_ne.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=arxiv_cs_ne.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({arxiv_cs_ne.ROUTE_NAME: route}))


async def test_arxiv_cs_ne_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(arxiv_cs_ne, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="arxiv-cs-ne", path_type="cs-ne")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "arxiv-cs-ne"


async def test_arxiv_cs_ne_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="arxiv-cs-ne", path_type="hot")
        )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/arxiv-cs-ne",
            "query_string": b"type=cs-ne",
            "headers": [],
        }
    )


async def test_arxiv_cs_ne_uses_official_atom_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-29T18:20:00+00:00", ATOM_SAMPLE)

    monkeypatch.setattr(arxiv_cs_ne, "get", fake_get)
    result = await arxiv_cs_ne.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": arxiv_cs_ne.FEED_URL,
        "no_cache": True,
        "response_type": "text",
    }
    assert result.total == 1
    assert result.data[0].id == "http://arxiv.org/abs/2608.27150v1"
    assert result.data[0].author == "Ada Researcher"
    assert result.data[0].desc == "A compact abstract."
    assert result.data[0].timestamp == 1787999400000
    assert result.data[0].url == "https://arxiv.org/abs/2608.27150v1"


async def test_arxiv_cs_ne_rejects_empty_feed(monkeypatch) -> None:
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-08-29T18:20:00+00:00", "<feed />")

    monkeypatch.setattr(arxiv_cs_ne, "get", fake_get)

    with pytest.raises(RuntimeError, match="non-empty Atom feed"):
        await arxiv_cs_ne.handle_route(_request(), no_cache=True)
