from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import lichess
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_lichess_extracts_perf_leaderboard(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/api/player/top/100/blitz")
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "users": [
                    {
                        "id": "ediz_gurel",
                        "username": "Ediz_Gurel",
                        "title": "GM",
                        "patron": True,
                        "perfs": {"blitz": {"rating": 3011, "progress": 12}},
                    },
                    {"id": "invalid", "username": "No rating", "perfs": {}},
                ]
            },
        )

    monkeypatch.setattr(lichess, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/lichess", "query_string": b"type=blitz", "headers": []}
    )
    route_data = await lichess.handle_route(request)

    assert route_data.type == "超快棋"
    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "ediz_gurel"
    assert item.hot == 3011
    assert item.desc == "头衔：GM · 近期变化：+12 · Lichess Patron"
    assert item.url == "https://lichess.org/@/Ediz_Gurel/perf/blitz"


def test_lichess_declares_all_public_perf_boards():
    assert len(lichess.type_map) == 13
    assert {"bullet", "blitz", "rapid", "classical"}.issubset(lichess.type_map)
