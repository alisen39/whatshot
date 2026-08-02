from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import coingecko
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_coingecko_market_cap_board(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == coingecko._MARKETS_URL
        assert kwargs["params"]["vs_currency"] == "usd"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            [
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "current_price": 65000,
                    "price_change_percentage_24h": 2.5,
                    "market_cap": 1200000000000,
                    "image": "https://example.com/btc.png",
                }
            ],
        )

    monkeypatch.setattr(coingecko, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/coingecko", "query_string": b"type=market-cap", "headers": []}
    )
    route_data = await coingecko.handle_route(request)

    assert route_data.type == "全球加密货币市值榜"
    assert route_data.data[0].id == "bitcoin"
    assert route_data.data[0].title == "Bitcoin (BTC)"
    assert route_data.data[0].hot == 1200000000000


@pytest.mark.asyncio
async def test_coingecko_trending_board(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == coingecko._TRENDING_URL
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "coins": [
                    {
                        "item": {
                            "id": "cash-cat",
                            "symbol": "CASHCAT",
                            "name": "Cash Cat",
                            "market_cap_rank": 265,
                            "large": "https://example.com/cashcat.png",
                            "data": {
                                "price": 0.1,
                                "price_change_percentage_24h": {"usd": -5.25},
                            },
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(coingecko, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/coingecko", "query_string": b"type=trending", "headers": []}
    )
    route_data = await coingecko.handle_route(request)

    assert route_data.type == "24h 搜索趋势榜"
    assert route_data.data[0].id == "cash-cat"
    assert "市值排名：265" in route_data.data[0].desc
    assert route_data.data[0].cover == "https://example.com/cashcat.png"


@pytest.mark.asyncio
async def test_coingecko_categories_board(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == coingecko._CATEGORIES_URL
        assert kwargs["params"] == {"order": "market_cap_desc"}
        return RequestResult(
            False,
            "2026-07-19T00:00:00+00:00",
            [
                {
                    "id": "layer-1",
                    "name": "Layer 1",
                    "market_cap": 123456789,
                    "volume_24h": 987654,
                    "market_cap_change_24h": -1.25,
                }
            ],
        )

    monkeypatch.setattr(coingecko, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/coingecko", "query_string": b"type=categories", "headers": []}
    )
    route_data = await coingecko.handle_route(request)

    assert route_data.type == "加密货币分类市值榜"
    assert route_data.data[0].id == "layer-1"
    assert route_data.data[0].hot == 123456789
    assert route_data.data[0].url == "https://www.coingecko.com/en/categories/layer-1"


@pytest.mark.asyncio
async def test_coingecko_derivatives_board_sorts_active_contracts_by_volume(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == coingecko._DERIVATIVES_URL
        return RequestResult(
            False,
            "2026-07-19T00:00:00+00:00",
            [
                {
                    "market": "Example Futures",
                    "symbol": "ETHUSDT",
                    "index_id": "ETH",
                    "contract_type": "perpetual",
                    "price": "3000",
                    "volume_24h": 1000,
                    "open_interest": 2000,
                    "funding_rate": 0.001,
                },
                {
                    "market": "Example Futures",
                    "symbol": "BTCUSDT",
                    "index_id": "BTC",
                    "contract_type": "perpetual",
                    "volume_24h": 5000,
                    "price_percentage_change_24h": -2.5,
                },
                {
                    "market": "Expired Futures",
                    "symbol": "BTC-OLD",
                    "contract_type": "futures",
                    "volume_24h": 999999,
                    "expired_at": "2025-01-01T00:00:00Z",
                },
            ],
        )

    monkeypatch.setattr(coingecko, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/coingecko", "query_string": b"type=derivatives", "headers": []}
    )
    route_data = await coingecko.handle_route(request)

    assert route_data.type == "加密衍生品 24h 成交额榜"
    assert [item.title for item in route_data.data] == [
        "Example Futures · BTCUSDT",
        "Example Futures · ETHUSDT",
    ]
    assert route_data.data[0].hot == 5000
    assert "排名：1" in route_data.data[0].desc


@pytest.mark.asyncio
async def test_coingecko_exchanges_board_sorts_by_btc_volume(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == coingecko._EXCHANGES_URL
        assert kwargs["params"] == {"per_page": "250", "page": "1"}
        return RequestResult(
            False,
            "2026-07-19T00:00:00+00:00",
            [
                {
                    "id": "small-exchange",
                    "name": "Small Exchange",
                    "trade_volume_24h_btc": 12.5,
                    "trust_score": 7,
                },
                {
                    "id": "large-exchange",
                    "name": "Large Exchange",
                    "trade_volume_24h_btc": 456.7,
                    "country": "Singapore",
                    "year_established": 2017,
                    "image": "https://example.com/logo.png",
                },
            ],
        )

    monkeypatch.setattr(coingecko, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/coingecko", "query_string": b"type=exchanges", "headers": []}
    )
    route_data = await coingecko.handle_route(request)

    assert route_data.type == "加密货币交易所 24h 成交额榜"
    assert [item.id for item in route_data.data] == ["large-exchange", "small-exchange"]
    assert route_data.data[0].hot == 457
    assert route_data.data[0].url == "https://www.coingecko.com/en/exchanges/large-exchange"
    assert "地区：Singapore" in route_data.data[0].desc
