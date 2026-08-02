from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import maven
from whats_hot_api.utils.http_client import RequestResult


POPULAR_HTML = """
<h2>Most Popular Packages in Last 90 Days</h2>
<ul>
  <li>
    <a data-test="component-card-name-link"
       href="/artifact/org.example/sample-lib">sample-lib</a>
    <div data-test="latest-version-metadata">2.1.0</div>
    <div data-test="published-metadata">5 days ago</div>
    <a data-test="used-in-metadata">1,234 projects</a>
  </li>
</ul>
<h2>Most Popular Namespaces in Last 90 Days</h2>
<ul>
  <li><a href="/namespace/org.example">org.example</a> 42 projects</li>
</ul>
"""

LATEST_JSON = {
    "response": {
        "docs": [
            {
                "id": "org.example:sample-lib",
                "g": "org.example",
                "a": "sample-lib",
                "latestVersion": "2.1.0",
                "p": "jar",
                "repositoryId": "central",
                "timestamp": 1781095941000,
                "versionCount": 9,
            }
        ]
    }
}


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/maven",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_id", "expected_title"),
    [
        ("popular-packages", "org.example:sample-lib", "sample-lib"),
        ("popular-namespaces", "org.example", "org.example"),
    ],
)
async def test_maven_popular_boards_parse_official_homepage(
    monkeypatch,
    board_type,
    expected_id,
    expected_title,
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == maven._CENTRAL_URL
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", POPULAR_HTML)

    monkeypatch.setattr(maven, "get", fake_get)
    route_data = await maven.handle_route(_request(board_type))
    item = route_data.data[0]

    assert item.id == expected_id
    assert item.title == expected_title
    assert item.hot is None
    assert "近 90 天热门排名：1" in item.desc
    assert route_data.total == 1


@pytest.mark.asyncio
async def test_maven_latest_uses_global_wildcard_and_version_event_id(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == maven._SEARCH_URL
        assert kwargs["params"] == {
            "q": "*:*",
            "rows": "100",
            "wt": "json",
        }
        assert kwargs["response_type"] == "json"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", LATEST_JSON)

    monkeypatch.setattr(maven, "get", fake_get)
    route_data = await maven.handle_route(_request("latest"))
    item = route_data.data[0]

    assert item.id == "org.example:sample-lib:2.1.0"
    assert item.title == "sample-lib 2.1.0"
    assert item.author == "org.example"
    assert item.timestamp == 1781095941000
    assert item.url.endswith("/artifact/org.example/sample-lib/2.1.0")
    assert "版本数：9" in item.desc
