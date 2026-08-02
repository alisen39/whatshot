from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import hackernews
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/hackernews",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "endpoint", "item_type", "label"),
    [
        ("best", "beststories.json", "story", "Best"),
        ("show", "showstories.json", "story", "Show HN"),
        ("ask", "askstories.json", "story", "Ask HN"),
        ("new", "newstories.json", "story", "New"),
        ("jobs", "jobstories.json", "job", "Jobs"),
    ],
)
async def test_hackernews_owns_all_boards(monkeypatch, board_type, endpoint, item_type, label):
    async def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        if url.endswith(endpoint):
            return RequestResult(False, "hn-update", [42])
        return RequestResult(
            False,
            "hn-item-update",
            {
                "id": 42,
                "type": item_type,
                "title": "A Hacker News item",
                "score": 321,
                "descendants": 7,
                "time": 1783330000,
                "url": "https://example.com/story",
            },
        )

    monkeypatch.setattr(hackernews, "get", fake_get)
    result = await hackernews.handle_route(_request(board_type), no_cache=True)

    assert result.name == "hackernews"
    assert result.type == label
    assert result.data[0].id == "42"
    assert result.data[0].url == "https://example.com/story"
    assert result.data[0].timestamp == 1783330000000


def test_hackernews_filters_invalid_items_and_uses_discussion_url():
    assert hackernews._valid_ids([10, 10, "11", -1, *range(11, 50)])[:3] == [10, 11, 12]
    assert len(hackernews._valid_ids([10, 10, "11", -1, *range(11, 50)])) == 30
    item = hackernews._item_from_row(
        {"id": 123, "type": "job", "title": "Example is hiring", "time": 1784336468},
        "jobs",
    )
    assert item is not None
    assert item.url == "https://news.ycombinator.com/item?id=123"
    assert hackernews._item_from_row({"id": 124, "type": "job", "title": "Wrong"}, "new") is None
