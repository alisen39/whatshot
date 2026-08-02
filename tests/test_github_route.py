from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import github
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/github",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_github_blog_board_uses_official_feed(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://github.blog/feed/"
        return RequestResult(
            False,
            "github-update",
            "<rss><channel><item><guid>1</guid><title>GitHub post</title>"
            "<link>https://github.blog/post</link></item></channel></rss>",
        )

    monkeypatch.setattr(github, "get", fake_get)
    result = await github.handle_route(_request("blog"), no_cache=True)

    assert result.name == "github"
    assert result.type == "GitHub Blog"
    assert result.link == "https://github.blog/"
    assert result.data[0].title == "GitHub post"
