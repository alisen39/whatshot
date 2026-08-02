from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import lesswrong
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "query_fragment"),
    [
        ("frontpage", 'view: "frontpage"'),
        ("curated", 'view: "curated"'),
        ("new", 'view: "new"'),
        ("shortform", 'view: "shortform"'),
        ("top-week", 'view: "top", after:'),
        ("top-all", 'view: "top", limit: 50'),
    ],
)
async def test_lesswrong_builds_board_queries(monkeypatch, board_type, query_fragment):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == lesswrong._GRAPHQL_URL
        assert query_fragment in kwargs["body"]["query"]
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": {
                    "posts": {
                        "results": [
                            {
                                "_id": "abc123",
                                "title": "A LessWrong post",
                                "slug": "a-lesswrong-post",
                                "user": {"displayName": "Author"},
                                "baseScore": 42,
                                "commentCount": 7,
                                "postedAt": "2026-07-15T00:00:00Z",
                                "tags": [{"name": "AI"}],
                            }
                        ]
                    }
                }
            },
        )

    monkeypatch.setattr(lesswrong, "post", fake_post)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/lesswrong",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )
    route_data = await lesswrong.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == lesswrong.type_map[board_type]
    assert item.id == "abc123"
    assert item.hot == 42
    assert item.desc == "评论：7 · 标签：AI"
    assert item.url == "https://www.lesswrong.com/posts/abc123/a-lesswrong-post"


def test_lesswrong_period_queries_use_date_stable_cutoffs():
    first = lesswrong._posts_query("top-week")
    second = lesswrong._posts_query("top-week")
    assert first == second
    assert "T00:00:00+00:00" in first
