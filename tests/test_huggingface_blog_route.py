from __future__ import annotations

from types import SimpleNamespace

import pytest
from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import huggingface_blog


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=huggingface_blog.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=huggingface_blog.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({huggingface_blog.ROUTE_NAME: route}))


async def test_grouped_blog_type_reaches_huggingface_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_get_list(no_cache: bool) -> dict:
        observed["no_cache"] = no_cache
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(huggingface_blog, "_get_list", fake_get_list)

    result = await _fetch_service().fetch(
        FetchRequest(site="huggingface-blog", path_type="blog")
    )

    assert observed == {"no_cache": False}
    assert result.data.name == "huggingface-blog"


async def test_huggingface_blog_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="huggingface-blog", path_type="hot")
        )
