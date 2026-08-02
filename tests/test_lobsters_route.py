from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import lobsters
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/lobsters", "query_string": f"type={board_type}".encode(), "headers": []})


@pytest.mark.asyncio
async def test_lobsters_active_board_uses_owned_official_endpoint(monkeypatch):
    async def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        assert url == "https://lobste.rs/active.json"
        return RequestResult(False, "lobsters-update", [{
            "short_id": "abc123", "title": "Active story", "comments_url": "https://lobste.rs/s/abc123/story",
            "comment_count": 7, "score": 10, "created_at": "2026-07-30T00:00:00Z",
        }])

    monkeypatch.setattr(lobsters, "get", fake_get)
    result = await lobsters.handle_route(_request("active"), no_cache=True)
    assert result.name == "lobsters"
    assert result.type == "Active"
    assert result.data[0].id == "abc123"
