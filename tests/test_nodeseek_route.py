from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import nodeseek


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=nodeseek.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=nodeseek.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({nodeseek.ROUTE_NAME: route}))


async def test_nodeseek_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(nodeseek, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="nodeseek", path_type="all")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "nodeseek"


async def test_nodeseek_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="nodeseek", path_type="hot")
        )
