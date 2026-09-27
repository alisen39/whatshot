from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import nature_bmi


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=nature_bmi.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=nature_bmi.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({nature_bmi.ROUTE_NAME: route}))


async def test_nature_bmi_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(nature_bmi, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="nature-bmi", path_type="bmi")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "nature-bmi"


async def test_nature_bmi_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="nature-bmi", path_type="hot")
        )


@pytest.mark.asyncio
async def test_feed_items_parse(monkeypatch) -> None:
    from starlette.requests import Request

    from whats_hot_api.utils.http_client import RequestResult

    feed_xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        '<item><title>Research update one</title>'
        '<link>https://www.nature.com/articles/a1</link></item>'
        "</channel></rss>"
    )

    async def fake_get(**kwargs):
        return RequestResult(False, "2026-09-14T00:00:00+00:00", feed_xml)

    monkeypatch.setattr(nature_bmi, "get", fake_get)
    route_data = await nature_bmi.handle_route(
        Request({"type": "http", "method": "GET", "path": "/nature-bmi", "headers": []}),
        no_cache=True,
    )
    assert route_data.total == 1
    assert route_data.data[0].title == "Research update one"


@pytest.mark.asyncio
async def test_interstitial_page_raises_instead_of_empty_success(monkeypatch) -> None:
    from starlette.requests import Request

    from whats_hot_api.utils.http_client import RequestResult

    async def fake_get(**kwargs):
        return RequestResult(
            False,
            "2026-09-14T00:00:00+00:00",
            "<!doctype html><html><body><noscript>Enable JavaScript</noscript></body></html>",
        )

    monkeypatch.setattr(nature_bmi, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await nature_bmi.handle_route(
            Request({"type": "http", "method": "GET", "path": "/nature-bmi", "headers": []}),
            no_cache=True,
        )
