from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import kr36_news, runway_changelog


def _service_for(route_module) -> FetchService:
    route = SimpleNamespace(
        handle_route=route_module.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=route_module.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({route_module.ROUTE_NAME: route}))


@pytest.mark.parametrize(
    "route_module,path_type",
    [(kr36_news, "latest"), (runway_changelog, "changelog")],
)
async def test_declared_board_type_reaches_route(monkeypatch, route_module, path_type) -> None:
    observed: dict[str, object] = {}

    if route_module is kr36_news:
        async def fake_fetch(**kwargs):
            observed["no_cache"] = kwargs["no_cache"]
            return {"from_cache": False, "update_time": "2026-09-14T00:00:00+00:00", "data": []}

        monkeypatch.setattr(kr36_news, "fetch_rsshub_feed", fake_fetch)
    else:
        async def fake_get_list(no_cache: bool) -> dict:
            observed["no_cache"] = no_cache
            return {"from_cache": False, "update_time": "2026-09-14T00:00:00+00:00", "data": []}

        monkeypatch.setattr(route_module, "_get_list", fake_get_list)

    result = await _service_for(route_module).fetch(
        FetchRequest(site=route_module.ROUTE_NAME, path_type=path_type)
    )

    assert observed == {"no_cache": False}
    assert result.data.name == route_module.ROUTE_NAME


@pytest.mark.parametrize(
    "route_module,path_type",
    [(kr36_news, "hot"), (runway_changelog, "hot")],
)
async def test_undeclared_board_type_is_rejected(route_module, path_type) -> None:
    with pytest.raises(FetchTypeNotFoundError):
        await _service_for(route_module).fetch(
            FetchRequest(site=route_module.ROUTE_NAME, path_type=path_type)
        )
