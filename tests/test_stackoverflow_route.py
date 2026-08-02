from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import stackoverflow
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_path", "expected_sort"),
    [
        ("hot", "/questions", "hot"),
        ("unanswered", "/questions/unanswered", "votes"),
        ("featured", "/questions/featured", "activity"),
    ],
)
async def test_stackoverflow_boards(monkeypatch, board_type, expected_path, expected_sort):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith(expected_path)
        assert kwargs["params"]["sort"] == expected_sort
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "items": [
                    {
                        "question_id": 123,
                        "title": "Rust &amp; async",
                        "score": 9,
                        "answer_count": 2,
                        "view_count": 100,
                        "bounty_amount": 50,
                        "tags": ["rust", "async"],
                        "owner": {"display_name": "Ferris&#39;s friend"},
                        "creation_date": 1700000000,
                        "link": "https://stackoverflow.com/questions/123/rust-async",
                    }
                ]
            },
        )

    monkeypatch.setattr(stackoverflow, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/stackoverflow",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )
    route_data = await stackoverflow.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == stackoverflow.type_map[board_type]
    assert item.id == "123"
    assert item.title == "Rust & async"
    assert item.author == "Ferris's friend"
    assert item.hot == 9
    assert item.timestamp == 1700000000000
    assert "回答：2" in item.desc
    assert ("悬赏：50" in item.desc) is (board_type == "featured")
