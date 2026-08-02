from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import investing
from whats_hot_api.utils.http_client import RequestResult


def _request(query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/investing",
        "query_string": query_string,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_investing_uses_verified_economic_indicators_feed(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/news_95.rss")
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            """<?xml version="1.0"?><rss><channel><item>
                <title>Crude Oil Inventories Fall Less Than Expected</title>
                <link>https://www.investing.com/news/economic-indicators/example-1</link>
                <guid>example-1</guid><author>Investing.com</author>
                <pubDate>Wed, 15 Jul 2026 12:00:00 GMT</pubDate>
            </item></channel></rss>""",
        )

    monkeypatch.setattr(investing, "get", fake_get)

    route_data = await investing.handle_route(_request(b"type=indicators"))
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "经济指标"
    assert item.id == "example-1"
    assert item.contentStatus == "summary"
    assert item.tags == ["经济指标"]
    assert item.timestamp == 1784116800000


@pytest.mark.asyncio
async def test_investing_falls_back_to_stock_market(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/news_25.rss")
        return RequestResult(False, "2026-07-16T00:00:00+00:00", "<rss><channel /></rss>")

    monkeypatch.setattr(investing, "get", fake_get)
    route_data = await investing.handle_route(_request(b"type=unknown"))
    assert route_data.type == "股票市场"
    assert route_data.total == 0
