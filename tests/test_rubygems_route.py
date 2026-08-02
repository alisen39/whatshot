from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import rubygems
from whats_hot_api.utils.http_client import RequestResult


STATS_HTML = """
<article>
  <h3><span>All Time Most Downloaded</span></h3>
  <div>
    <h3><a href="/gems/bundler">bundler</a></h3>
    <div data-controller="stats"><span>3,564,774,418</span></div>
  </div>
</article>
"""

ACTIVITY_ROWS = [
    {
        "name": "native-gem",
        "version": "1.2.3",
        "version_created_at": "2026-07-16T17:15:04.769Z",
        "downloads": 9_999,
        "version_downloads": 321,
        "platform": "x86_64-linux-musl",
        "authors": "Ruby Author",
        "info": "Native extension.",
        "licenses": ["MIT"],
        "project_uri": "https://rubygems.org/gems/native-gem",
    }
]


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/rubygems",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_rubygems_downloads_parses_official_stats(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://rubygems.org/stats"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", STATS_HTML)

    monkeypatch.setattr(rubygems, "get", fake_get)
    route_data = await rubygems.handle_route(_request("downloads"))
    item = route_data.data[0]

    assert route_data.type == "累计下载"
    assert item.id == "bundler"
    assert item.hot == 3_564_774_418
    assert item.url == "https://rubygems.org/gems/bundler"


@pytest.mark.asyncio
async def test_rubygems_latest_deduplicates_project_rows(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/activity/latest.json")
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            ACTIVITY_ROWS + ACTIVITY_ROWS,
        )

    monkeypatch.setattr(rubygems, "get", fake_get)
    route_data = await rubygems.handle_route(_request("latest"))
    item = route_data.data[0]

    assert route_data.total == 1
    assert item.id == "native-gem"
    assert item.hot == 9_999
    assert item.timestamp is None
    assert item.url == "https://rubygems.org/gems/native-gem"


@pytest.mark.asyncio
async def test_rubygems_updated_preserves_platform_identity(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/activity/just_updated.json")
        return RequestResult(False, "2026-07-17T00:00:00+00:00", ACTIVITY_ROWS)

    monkeypatch.setattr(rubygems, "get", fake_get)
    route_data = await rubygems.handle_route(_request("updated"))
    item = route_data.data[0]

    assert item.id == "native-gem:1.2.3:x86_64-linux-musl"
    assert item.hot == 321
    assert item.timestamp == 1_784_222_104_769
    assert "平台：x86_64-linux-musl" in item.desc
    assert item.url.endswith(
        "/gems/native-gem/versions/1.2.3-x86_64-linux-musl"
    )
