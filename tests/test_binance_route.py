from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import binance
from whats_hot_api.utils.http_client import RequestResult


ROWS = [
    {
        "symbol": "BTCUSDT",
        "lastPrice": "120000.00",
        "priceChangePercent": "2.5",
        "quoteVolume": "500000000.00",
    },
    {
        "symbol": "ALTUSDT",
        "lastPrice": "1.25",
        "priceChangePercent": "20.0",
        "quoteVolume": "2000000.00",
    },
    {
        "symbol": "THINUSDT",
        "lastPrice": "0.01",
        "priceChangePercent": "999.0",
        "quoteVolume": "10.00",
    },
    {
        "symbol": "BTCIDR",
        "lastPrice": "1000000000",
        "priceChangePercent": "50.0",
        "quoteVolume": "999999999999",
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_ids"),
    [
        ("volume", ["BTCUSDT", "ALTUSDT", "THINUSDT"]),
        ("gainers", ["ALTUSDT", "BTCUSDT"]),
        ("losers", ["BTCUSDT", "ALTUSDT"]),
    ],
)
async def test_binance_builds_comparable_usdt_boards(
    monkeypatch, board_type, expected_ids
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == binance._TICKER_URL
        return RequestResult(False, "2026-07-16T00:00:00+00:00", ROWS)

    monkeypatch.setattr(binance, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/binance",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )
    route_data = await binance.handle_route(request)

    assert [item.id for item in route_data.data] == expected_ids
    assert all(item.title.endswith("/USDT") for item in route_data.data)
    assert route_data.data[0].url.endswith("_USDT?type=spot")


def test_binance_decimal_tolerates_invalid_values():
    assert binance._decimal(None) == 0
    assert binance._decimal("not-a-number") == 0
