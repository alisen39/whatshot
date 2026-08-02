from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import defillama
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/defillama",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_defillama_sorts_and_maps_protocol_tvl(monkeypatch):
    rows = [
        {
            "slug": "aave-v3",
            "name": "Aave V3",
            "symbol": "AAVE",
            "category": "Lending",
            "tvl": 13_565_950_915.4,
            "mcap": 2_500_000_000,
            "change_1d": -0.89,
            "change_7d": 10.53,
            "chains": ["Ethereum", "Polygon"],
            "logo": "https://icons.example/aave",
        },
        {
            "slug": "lido",
            "name": "Lido",
            "symbol": "LDO",
            "category": "Liquid Staking",
            "tvl": 17_223_115_654.8,
            "change_1d": -3,
            "change_7d": 7.96,
            "chains": ["Ethereum"],
        },
    ]

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == defillama._PROTOCOLS_URL
        return RequestResult(False, "2026-07-17T00:00:00+00:00", rows)

    monkeypatch.setattr(defillama, "get", fake_get)
    route_data = await defillama.handle_route(_request())

    assert route_data.type == "协议 TVL 排行榜"
    assert [item.id for item in route_data.data] == ["lido", "aave-v3"]
    assert route_data.data[0].title == "Lido (LDO)"
    assert route_data.data[0].hot == 17_223_115_655
    assert "排名：1" in route_data.data[0].desc
    assert "TVL：$17.22B" in route_data.data[0].desc
    assert "24h：-3.00%" in route_data.data[0].desc
    assert route_data.data[1].cover == "https://icons.example/aave"
    assert route_data.data[1].url == "https://defillama.com/protocol/aave-v3"


def test_defillama_requires_stable_slug_and_finite_nonnegative_tvl():
    assert defillama._is_rankable({"slug": "aave-v3", "name": "Aave", "tvl": 1})
    assert not defillama._is_rankable({"slug": "", "name": "Aave", "tvl": 1})
    assert not defillama._is_rankable({"slug": "BAD SLUG", "name": "Aave", "tvl": 1})
    assert not defillama._is_rankable({"slug": "aave", "name": "", "tvl": 1})
    assert not defillama._is_rankable({"slug": "aave", "name": "Aave", "tvl": -1})
    assert not defillama._is_rankable({"slug": "aave", "name": "Aave", "tvl": "nan"})
