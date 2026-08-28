from __future__ import annotations

from types import SimpleNamespace

import pytest

from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import FetchRequest, FetchService, FetchTypeNotFoundError
from whats_hot_api.routes.hotlist import anthropic_news


def _fetch_service() -> FetchService:
    route = SimpleNamespace(
        handle_route=anthropic_news.handle_route,
        category="hotlist",
        category_label="热榜",
        metadata=anthropic_news.ROUTE_META,
        validate_type=True,
    )
    return FetchService(RouteCatalog({anthropic_news.ROUTE_NAME: route}))


async def test_anthropic_news_type_reaches_route_feed(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_fetch_rsshub_feed(**kwargs) -> dict:
        observed.update(kwargs)
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(anthropic_news, "fetch_rsshub_feed", fake_fetch_rsshub_feed)

    result = await _fetch_service().fetch(
        FetchRequest(site="anthropic-news", path_type="news")
    )

    assert observed.get("no_cache") is False
    assert observed.get("route_path") == "/anthropic/news"
    assert result.data.name == "anthropic-news"


async def test_anthropic_news_rejects_undeclared_type() -> None:
    with pytest.raises(FetchTypeNotFoundError, match="Unknown type 'hot'"):
        await _fetch_service().fetch(
            FetchRequest(site="anthropic-news", path_type="hot")
        )
