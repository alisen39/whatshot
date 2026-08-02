from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import pypi
from whats_hot_api.utils.http_client import RequestResult


DOWNLOAD_HTML = """
<section>
  <h1>Most downloaded PyPI packages</h1>
  <table><tr>
    <td><table><tr><td>1</td><td><a href="/packages/day-pkg">day-pkg</a></td><td>1,200</td></tr></table></td>
    <td><table><tr><td>1</td><td><a href="/packages/week-pkg">week-pkg</a></td><td>7,000</td></tr></table></td>
    <td><table><tr><td>1</td><td><a href="/packages/month-pkg">month-pkg</a></td><td>30,000</td></tr></table></td>
  </tr></table>
</section>
"""

UPDATES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>sample-pkg 2.0.0</title>
  <link>https://pypi.org/project/sample-pkg/2.0.0/</link>
  <description>A useful package.</description>
  <author>maintainer@example.com</author>
  <pubDate>Thu, 16 Jul 2026 17:08:12 GMT</pubDate>
</item></channel></rss>
"""

NEW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>brand-new added to PyPI</title>
  <link>https://pypi.org/project/brand-new/</link>
  <guid>https://pypi.org/project/brand-new/</guid>
  <description>New project.</description>
  <pubDate>Thu, 16 Jul 2026 17:04:28 GMT</pubDate>
</item></channel></rss>
"""

SIZE_HTML = """
<table>
  <caption>Statistics by project</caption>
  <tbody>
    <tr><th>All of PyPI</th><td>42.5 TB</td></tr>
    <tr><th>large-pkg</th><td>606.3 GB</td></tr>
  </tbody>
</table>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/pypi",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_title", "expected_hot"),
    [
        ("day", "day-pkg", 1_200),
        ("week", "week-pkg", 7_000),
        ("month", "month-pkg", 30_000),
    ],
)
async def test_pypi_download_boards(monkeypatch, board_type, expected_title, expected_hot):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://pypistats.org/top"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", DOWNLOAD_HTML)

    monkeypatch.setattr(pypi, "get", fake_get)
    route_data = await pypi.handle_route(_request(board_type))
    item = route_data.data[0]

    assert route_data.type == pypi.type_map[board_type]
    assert item.id == expected_title
    assert item.title == expected_title
    assert item.hot == expected_hot
    assert item.url == f"https://pypi.org/project/{expected_title}/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "xml", "expected_id", "expected_title"),
    [
        ("updates", UPDATES_XML, "sample-pkg:2.0.0", "sample-pkg 2.0.0"),
        ("new", NEW_XML, "brand-new", "brand-new"),
    ],
)
async def test_pypi_official_rss_boards(
    monkeypatch,
    board_type,
    xml,
    expected_id,
    expected_title,
):
    async def fake_get(**kwargs):  # noqa: ANN003
        expected_feed = "updates" if board_type == "updates" else "packages"
        assert kwargs["url"] == f"https://pypi.org/rss/{expected_feed}.xml"
        assert "application/rss+xml" in kwargs["headers"]["Accept"]
        return RequestResult(False, "2026-07-17T00:00:00+00:00", xml)

    monkeypatch.setattr(pypi, "get", fake_get)
    route_data = await pypi.handle_route(_request(board_type))
    item = route_data.data[0]

    assert item.id == expected_id
    assert item.title == expected_title
    assert item.timestamp == (
        1_784_221_692_000 if board_type == "updates" else 1_784_221_468_000
    )
    assert item.url.startswith("https://pypi.org/project/")


@pytest.mark.asyncio
async def test_pypi_size_board_skips_registry_total(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://pypi.org/stats/"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", SIZE_HTML)

    monkeypatch.setattr(pypi, "get", fake_get)
    route_data = await pypi.handle_route(_request("size"))
    item = route_data.data[0]

    assert route_data.total == 1
    assert item.id == "large-pkg"
    assert item.hot == 606_300_000_000
    assert "606.3 GB" in item.desc
