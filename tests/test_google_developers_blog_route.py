from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import google_developers_blog


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=google_developers_blog.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=google_developers_blog.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({google_developers_blog.ROUTE_NAME: route}))


async def test_google_developers_blog_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(google_developers_blog, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="google-developers-blog", path_type="developers")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "google-developers-blog"


async def test_google_developers_blog_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="google-developers-blog", path_type="hot")
        )
