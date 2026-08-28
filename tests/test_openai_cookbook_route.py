from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import openai_cookbook
from whats_hot_api.utils.http_client import RequestResult


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=openai_cookbook.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=openai_cookbook.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({openai_cookbook.ROUTE_NAME: route}))


async def test_cookbook_type_reaches_official_atom_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get(*args, **kwargs):
        observed.update(kwargs)
        return RequestResult(False, "2026-08-28T00:00:00+00:00", SAMPLE_ATOM)

    monkeypatch.setattr(openai_cookbook, "get", fake_get)
    result = await _fetch_service().fetch(
        FetchRequest(site="openai-cookbook", path_type="cookbook")
    )

    assert observed["url"] == "https://github.com/openai/openai-cookbook/commits/main.atom"
    assert result.data.name == "openai-cookbook"
    assert result.data.total == 1


async def test_openai_cookbook_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="openai-cookbook", path_type="hot")
        )


@pytest.mark.asyncio
async def test_openai_cookbook_fails_explicitly_on_empty_feed(monkeypatch):
    async def fake_get(*args, **kwargs):
        return RequestResult(False, "2026-08-28T00:00:00+00:00", '<feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    monkeypatch.setattr(openai_cookbook, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/openai-cookbook/cookbook", "query_string": b"", "headers": []})
    with pytest.raises(RuntimeError, match="no usable items"):
        await openai_cookbook.handle_route(request, no_cache=True)


SAMPLE_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><id>tag:github.com,2008:Grit::Commit/abc</id>'
    '<title>Update examples/a_binary_tokens.ipynb</title>'
    '<link href="https://github.com/openai/openai-cookbook/commit/abc"/></entry>'
    '</feed>'
)
