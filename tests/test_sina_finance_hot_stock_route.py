from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import sina_finance
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", sina_finance.hot_stock_type)
async def test_sina_finance_hot_stock_boards(monkeypatch, board_type):
    expected_market = sina_finance.hot_stock_type[board_type]["market"]

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["market"] == expected_market
        assert "StockSelectionService.getHotStocks" in kwargs["url"]
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "result": {
                    "data": [{
                        "symbol": "sh600584",
                        "market": "cn",
                        "name": "长电科技",
                        "pv": "34358",
                        "uv_rank_chg": "2",
                        "uptime": "2026-07-15 23:30:48",
                        "news": {"title": "关联新闻"},
                    }]
                }
            },
        )

    monkeypatch.setattr(sina_finance, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/sina-finance",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })
    route_data = await sina_finance.handle_route(request)

    item = route_data.data[0]
    assert route_data.kind == "hotlist"
    assert route_data.type == sina_finance.hot_stock_type[board_type]["name"]
    assert item.id == "cn:sh600584"
    assert item.hot == 34358
    assert "排名变化：+2" in item.desc
    assert item.url.endswith("/sh600584")
