from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem, NewsFlashItem
from whats_hot_api.routes.newsflash import techcrunch_robotics
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = """<?xml version="1.0"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
  <guid>https://techcrunch.com/?p=3139375</guid>
  <title>Robotics example</title>
  <link>https://techcrunch.com/2026/08/26/robotics-example/</link>
  <dc:creator>Lucas Ropek</dc:creator>
  <pubDate>Wed, 26 Aug 2026 15:00:00 +0000</pubDate>
  <category>AI</category><category>Robotics</category><category>AI</category>
  <description>A verified RSS excerpt.</description>
</item></channel></rss>"""


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/techcrunch-robotics/robotics",
            "query_string": b"type=robotics",
            "headers": [],
        }
    )


def _item() -> ListItem:
    return ListItem(
        id="https://techcrunch.com/?p=3139375",
        title="Robotics example",
        author="Lucas Ropek",
        desc="A verified RSS excerpt.",
        timestamp=1787756400000,
        url="https://techcrunch.com/2026/08/26/robotics-example/",
    )


def test_normalizes_robotics_publication_as_newsflash() -> None:
    assert techcrunch_robotics._as_newsflash(_item(), ["AI", "Robotics"]) == NewsFlashItem(
        id="https://techcrunch.com/?p=3139375",
        title="Robotics example",
        content="A verified RSS excerpt.",
        summary="A verified RSS excerpt.",
        contentStatus="summary",
        source="Lucas Ropek",
        tags=["AI", "Robotics"],
        timestamp=1787756400000,
        url="https://techcrunch.com/2026/08/26/robotics-example/",
        mobileUrl="https://techcrunch.com/2026/08/26/robotics-example/",
    )


async def test_route_accepts_grouped_robotics_type(monkeypatch) -> None:
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(techcrunch_robotics, "get", fake_get)
    result = await techcrunch_robotics.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": "https://techcrunch.com/category/robotics/feed/",
        "no_cache": True,
        "response_type": "text",
        "headers": {
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Referer": "https://techcrunch.com/category/robotics/",
        },
    }
    assert result.kind == "newsflash"
    assert result.type == "Robotics"
    assert result.total == 1
    assert result.data[0].tags == ["AI", "Robotics"]


async def test_route_rejects_empty_feed(monkeypatch) -> None:
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-08-27T00:00:00+00:00", "<rss><channel/></rss>")

    monkeypatch.setattr(techcrunch_robotics, "get", fake_get)
    with pytest.raises(RuntimeError, match="no usable items"):
        await techcrunch_robotics.handle_route(_request())


def test_route_declares_only_grouped_robotics_type() -> None:
    assert techcrunch_robotics.ROUTE_META["params"]["type"]["type"] == {
        "robotics": "Robotics"
    }
