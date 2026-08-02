from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import thepaper
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/thepaper",
            "query_string": query,
            "headers": [],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "data_key", "label"),
    [
        ("hot", "hotNews", "热榜"),
        ("finance", "financialInformationNews", "财经资讯"),
        ("editor", "editorHandpicked", "编辑精选"),
    ],
)
async def test_thepaper_selects_sidebar_board(
    monkeypatch, board_type, data_key, label
):
    payload = {
        "data": {
            "hotNews": [],
            "financialInformationNews": [],
            "editorHandpicked": [],
        }
    }
    payload["data"][data_key] = [
        {
            "contId": "33594931",
            "name": f"{label}新闻",
            "pic": "https://img.example/cover.png",
            "praiseTimes": "30" if board_type != "finance" else None,
            "pubTimeLong": 1_784_143_578_436,
            "nodeInfo": {"name": "澎湃快讯"},
        }
    ]

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/contentapi/wwwIndex/rightSidebar")
        return RequestResult(False, "2026-07-16T00:00:00+00:00", payload)

    monkeypatch.setattr(thepaper, "get", fake_get)
    route_data = await thepaper.handle_route(
        _request(f"type={board_type}".encode())
    )

    assert route_data.type == label
    assert route_data.total == 1
    assert route_data.data[0].id == "33594931"
    assert route_data.data[0].author == "澎湃快讯"
    assert route_data.data[0].hot == (None if board_type == "finance" else 30)


@pytest.mark.asyncio
async def test_thepaper_unknown_type_falls_back_to_hot(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"data": {"hotNews": []}})

    monkeypatch.setattr(thepaper, "get", fake_get)
    route_data = await thepaper.handle_route(_request(b"type=unknown"))
    assert route_data.type == "热榜"
