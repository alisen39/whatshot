from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import producthunt
from whats_hot_api.utils.http_client import RequestResult

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:www.producthunt.com,2005:Post/1001</id>
    <published>2026-07-15T10:00:00-07:00</published>
    <title>Today One</title>
    <content type="html">&lt;p&gt;First tagline&lt;/p&gt;&lt;p&gt;Discussion | Link&lt;/p&gt;</content>
    <author><name>Jane</name></author>
    <link rel="alternate" href="https://www.producthunt.com/products/today-one"/>
  </entry>
  <entry>
    <id>tag:www.producthunt.com,2005:Post/1002</id>
    <published>2026-07-14T09:00:00-07:00</published>
    <title>Older Two</title>
    <content type="html">&lt;p&gt;Second tagline&lt;/p&gt;</content>
    <author><name>John</name></author>
    <link rel="alternate" href="https://www.producthunt.com/products/older-two"/>
  </entry>
</feed>"""


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/producthunt",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("board_type", "total"), [("today", 1), ("latest", 2)])
async def test_producthunt_feed_boards(monkeypatch, board_type, total):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == producthunt._FEED_URL
        return RequestResult(False, "2026-07-16T00:00:00+00:00", FEED)

    monkeypatch.setattr(producthunt, "get", fake_get)
    route_data = await producthunt.handle_route(_request(board_type))

    assert route_data.type == producthunt.type_map[board_type]
    assert route_data.total == total
    assert route_data.data[0].id == "1001"
    assert route_data.data[0].author == "Jane"
    assert route_data.data[0].desc == "First tagline"
    assert route_data.data[0].url == "https://www.producthunt.com/products/today-one"
