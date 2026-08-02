from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import reddit
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/reddit",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", ("programming", "saas", "machinelearning", "cogsci"))
async def test_reddit_native_boards_request_their_owned_subreddit(monkeypatch, board_type):
    captured: dict[str, object] = {}

    async def fake_get(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return RequestResult(
            False,
            "reddit-update",
            {"data": {"children": [{"data": {
                "id": "abc",
                "title": "Community discussion",
                "url": "https://example.com/post",
                "permalink": "/r/example/comments/abc/post/",
                "score": 99,
                "created_utc": 1783330100,
            }}]}},
        )

    monkeypatch.setattr(reddit, "get", fake_get)
    result = await reddit.handle_route(_request(board_type), no_cache=True)

    assert f"/r/{reddit.SUBREDDITS[board_type]}/hot.json" in captured["url"]
    assert result.name == "reddit"
    assert result.type == f"r/{reddit.SUBREDDITS[board_type]}"
    assert result.data[0].id == f"reddit-{reddit.SUBREDDITS[board_type]}-abc"
    assert result.data[0].hot == 99
    assert result.data[0].timestamp == 1783330100000


def test_reddit_ignores_stickied_and_invalid_urls():
    assert reddit._reddit_image({"thumbnail": "self"}) is None
    assert reddit._valid_url("https://example.com")
    assert not reddit._valid_url("ftp://example.com")
