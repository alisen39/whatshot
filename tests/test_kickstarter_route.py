from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import juejin, kickstarter
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_kickstarter_native_route_maps_technology_projects(monkeypatch):
    async def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        assert "category_id=16" in url
        return RequestResult(False, "kickstarter-update", {"projects": [{
            "id": 7, "name": "New gadget", "blurb": "Useful", "percent_funded": 125,
            "launched_at": 1783330100, "urls": {"web": {"project": "https://example.com/project"}},
            "photo": {"med": "https://example.com/image.png"},
        }]})

    monkeypatch.setattr(kickstarter, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/kickstarter-tech", "query_string": b"", "headers": []})
    result = await kickstarter.handle_route(request, no_cache=True)
    assert result.name == "kickstarter-tech"
    assert result.data[0].id == "kickstarter-7"
    assert result.data[0].hot == 125


@pytest.mark.asyncio
async def test_juejin_global_hot_board_replaces_retired_alias(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"category_id": "1", "type": "hot"}
        return RequestResult(False, "juejin-update", {"data": [{
            "content": {"content_id": "42", "title": "Hot post", "brief_content": "Summary"},
            "content_counter": {"hot_rank": 99},
        }]})

    monkeypatch.setattr(juejin, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/juejin", "query_string": b"type=hot", "headers": []})
    result = await juejin.handle_route(request, no_cache=True)
    assert result.name == "juejin"
    assert result.type == "全站热榜"
    assert result.data[0].id == "juejin-42"
