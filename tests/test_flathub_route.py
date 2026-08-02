from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import flathub
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/flathub",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_label"),
    [
        ("trending", "两周趋势榜"),
        ("popular", "月度热门榜"),
        ("recently-added", "新上架"),
        ("recently-updated", "最近更新"),
    ],
)
async def test_flathub_maps_official_collections(
    monkeypatch, board_type, expected_label
):
    row = {
        "app_id": "org.mozilla.firefox",
        "name": "Firefox",
        "summary": "Web browser",
        "developer_name": "Mozilla",
        "main_categories": "network",
        "project_license": "MPL-2.0",
        "installs_last_month": 208499,
        "trending": 18.75,
        "added_at": 1700000000,
        "updated_at": 1784032120,
        "verification_verified": True,
        "icon": "https://example.com/firefox.png",
    }

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == f"{flathub._API_BASE}/{board_type}"
        assert kwargs["params"] == {
            "page": "1",
            "per_page": "50",
            "locale": "en",
        }
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {"hits": [row]},
        )

    monkeypatch.setattr(flathub, "get", fake_get)
    route_data = await flathub.handle_route(_request(board_type))
    item = route_data.data[0]

    assert route_data.type == expected_label
    assert item.id == "org.mozilla.firefox"
    assert item.title == "Firefox"
    assert item.author == "Mozilla"
    assert item.cover == "https://example.com/firefox.png"
    assert item.url == "https://flathub.org/apps/org.mozilla.firefox"
    assert "近 30 天安装：208,499" in item.desc
    assert "趋势分：18.75" in item.desc
    assert "开发者已验证" in item.desc

    if board_type == "recently-added":
        assert item.timestamp == 1700000000000
        assert "上架：2023-11-14" in item.desc
    elif board_type == "recently-updated":
        assert item.timestamp == 1784032120000
        assert "更新：2026-07-14" in item.desc
    else:
        assert item.timestamp is None


def test_flathub_rejects_rows_without_stable_appstream_id():
    assert flathub._app_item({"app_id": "", "name": "No ID"}, 1, "popular") is None
    assert flathub._app_item({"app_id": "nodot", "name": "Bad ID"}, 1, "popular") is None
    assert flathub._app_item({"app_id": "org.example.App", "name": ""}, 1, "popular") is None
