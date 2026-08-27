from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import apple_newsroom


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=apple_newsroom.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=apple_newsroom.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({apple_newsroom.ROUTE_NAME: route}))


async def test_newsroom_type_reaches_apple_newsroom_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(apple_newsroom, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="apple-newsroom", path_type="newsroom")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "apple-newsroom"


async def test_apple_newsroom_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="apple-newsroom", path_type="hot")
        )
