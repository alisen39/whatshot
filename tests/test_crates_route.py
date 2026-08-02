from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import crates
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", crates.type_map)
async def test_crates_boards_use_official_sort_and_map_metrics(monkeypatch, board_type):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://crates.io/api/v1/crates"
        assert kwargs["params"] == {
            "page": "1",
            "per_page": "20",
            "sort": board_type,
        }
        assert kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
        assert "WhatsHot/" not in kwargs["headers"]["User-Agent"]
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {
                "crates": [
                    {
                        "id": "hashbrown",
                        "name": "hashbrown",
                        "newest_version": "0.17.1",
                        "description": "A Rust port of SwissTable",
                        "downloads": 1_961_980_998,
                        "recent_downloads": 535_944_124,
                        "updated_at": "2026-05-09T04:35:04.251Z",
                        "created_at": "2018-10-29T14:28:15.767024Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(crates, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/crates",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })
    route_data = await crates.handle_route(request)
    item = route_data.data[0]

    assert route_data.type == crates.type_map[board_type]
    assert item.id == "hashbrown"
    assert item.title == "hashbrown"
    assert item.url == "https://crates.io/crates/hashbrown"
    assert item.hot == (
        535_944_124 if board_type == "recent-downloads" else 1_961_980_998
    )
    assert "版本：0.17.1" in item.desc
    assert "累计下载：1,961,980,998" in item.desc
    assert "近期下载：535,944,124" in item.desc
    assert (item.timestamp is not None) is (
        board_type in {"recent-updates", "new"}
    )
