from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nuget
from whats_hot_api.utils.http_client import RequestResult


SEARCH_HTML = """
<li class="package">
  <img class="package-icon" src="https://example.test/icon.png">
  <a class="package-title" href="/packages/Sample.Package/2.0.0"
     data-package-id="Sample.Package" data-package-version="2.0.0">
    Sample.Package
  </a>
  <span class="package-by">
    <a data-owner="sample-owner">sample-owner</a>
  </span>
  <ul class="package-list">
    <li>1,234 total downloads</li>
    <li>last updated <span data-datetime="2026-07-16T17:21:57.3530000+00:00">date</span></li>
    <li class="package-tags"><a>json</a><a>dotnet</a></li>
  </ul>
  <div class="package-details">A useful package. <a>More information</a></div>
</li>
"""

STATS_HTML = """
<table aria-label="Packages with the most downloads"><tbody>
  <tr><td>1</td><td>Microsoft.Package</td><td>5,000</td></tr>
</tbody></table>
<table aria-label="Community packages with the most downloads"><tbody>
  <tr><td>1</td><td>Community.Package</td><td>2,000</td></tr>
</tbody></table>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/nuget",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", ["downloads", "recent"])
async def test_nuget_search_boards_parse_official_page(monkeypatch, board_type):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == nuget._SEARCH_URLS[board_type]
        return RequestResult(False, "2026-07-17T00:00:00+00:00", SEARCH_HTML)

    monkeypatch.setattr(nuget, "get", fake_get)
    route_data = await nuget.handle_route(_request(board_type))
    item = route_data.data[0]

    assert item.id == (
        "Sample.Package:2.0.0" if board_type == "recent" else "Sample.Package"
    )
    assert item.hot == 1_234
    assert item.author == "sample-owner"
    assert item.cover == "https://example.test/icon.png"
    assert "标签：json, dotnet" in item.desc
    assert (item.timestamp is not None) is (board_type == "recent")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_id", "expected_hot"),
    [
        ("six-weeks", "Microsoft.Package", 5_000),
        ("community-six-weeks", "Community.Package", 2_000),
    ],
)
async def test_nuget_stats_boards_select_distinct_tables(
    monkeypatch,
    board_type,
    expected_id,
    expected_hot,
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://www.nuget.org/stats/packages"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", STATS_HTML)

    monkeypatch.setattr(nuget, "get", fake_get)
    route_data = await nuget.handle_route(_request(board_type))
    item = route_data.data[0]

    assert item.id == expected_id
    assert item.hot == expected_hot
    assert item.url == f"https://www.nuget.org/packages/{expected_id}"
