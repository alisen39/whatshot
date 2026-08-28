from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import arxiv_cs_lg


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=arxiv_cs_lg.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=arxiv_cs_lg.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({arxiv_cs_lg.ROUTE_NAME: route}))


async def test_arxiv_cs_lg_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(arxiv_cs_lg, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="arxiv-cs-lg", path_type="cs-lg")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "arxiv-cs-lg"


async def test_arxiv_cs_lg_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="arxiv-cs-lg", path_type="hot")
        )
