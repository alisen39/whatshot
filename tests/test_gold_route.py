from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import GoldItem
from whats_hot_api.routes.gold import zdf
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_zdf_returns_dedicated_gold_items(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-30T00:00:00+00:00",
            {
                "code": 200,
                "data": {
                    "todayDate": "2026-07-30",
                    "todayPriceHK": "1262",
                    "todayPriceTzjt": 1200,
                    "baiJianHJPrice": "879",
                    "todayPriceHgjShi": 1188,
                    "touziZuboPrice": 528,
                    "touziZuboHJPrice": 391,
                },
            },
        )

    monkeypatch.setattr(zdf, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/zdf/default",
        "query_string": b"",
        "headers": [],
    })

    route_data = await zdf.handle_route(request, no_cache=True)

    assert route_data.kind == "gold"
    assert route_data.total == 4
    assert all(isinstance(item, GoldItem) for item in route_data.data)
    assert route_data.data[0].sellPrice == 1262
    assert route_data.data[0].recyclePrice == 879
    assert route_data.data[0].url == zdf.SOURCE_LINK
    assert route_data.data[0].mobileUrl is None
    assert "mobileUrl" not in route_data.data[0].model_dump(exclude_none=True)
    assert "hot" not in route_data.data[0].model_dump()
