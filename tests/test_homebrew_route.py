from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import homebrew
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", homebrew.type_map)
async def test_homebrew_analytics_boards(monkeypatch, board_type):
    package_type, window = board_type.split("-", 1)

    async def fake_get(**kwargs):  # noqa: ANN003
        expected = "cask-install" if package_type == "cask" else "install"
        assert f"/{expected}/{window}.json" in kwargs["url"]
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {
            "items": [{package_type: "openssl@3", "count": "499,854", "percent": 2.25}]
        })

    monkeypatch.setattr(homebrew, "get", fake_get)
    request = Request({
        "type": "http", "method": "GET", "path": "/homebrew",
        "query_string": f"type={board_type}".encode(), "headers": [],
    })
    route_data = await homebrew.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == homebrew.type_map[board_type]
    assert item.id == f"{package_type}:openssl@3"
    assert item.hot == 499854
    assert item.url == f"https://formulae.brew.sh/{package_type}/openssl@3"
