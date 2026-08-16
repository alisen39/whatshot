from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import GoldItem
from whats_hot_api.routes.gold import zdf
from whats_hot_api.utils.http_client import RequestResult


def test_zdf_declares_its_mainland_market_identity():
    assert zdf.ROUTE_META["params"]["type"]["type"] == {
        "mainland": "中国内地 · CNY"
    }


@pytest.mark.asyncio
async def test_zdf_returns_dedicated_gold_items(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(
            False,
            "2026-07-30T00:00:00+00:00",
            {
                "code": 200,
                "data": {
                    "goldPriceDailyListVO": [
                        {
                            "categoryName": "零售金价",
                            "goldPriceInfoListVO": [
                                {
                                    "displayName": "足金",
                                    "secondDisplayName": "（饰品、工艺品类）",
                                    "categoryGroup": 1,
                                    "sortOrder": 1,
                                    "isEnabled": True,
                                    "isShowInFrontend": True,
                                    "todayDate": "2026-07-30",
                                    "goldPrice": "1262",
                                },
                                {
                                    "displayName": "工艺金章金条类",
                                    "secondDisplayName": "",
                                    "categoryGroup": 1,
                                    "sortOrder": 2,
                                    "isEnabled": True,
                                    "isShowInFrontend": True,
                                    "todayDate": "2026-07-30",
                                    "goldPrice": 1200,
                                },
                                {
                                    "displayName": "投资黄金类",
                                    "secondDisplayName": "",
                                    "categoryGroup": 1,
                                    "sortOrder": 2,
                                    "isEnabled": True,
                                    "isShowInFrontend": True,
                                    "todayDate": "2026-07-30",
                                    "goldPrice": 1068,
                                },
                            ],
                        },
                        {
                            "categoryName": "黄金增值服务",
                            "goldPriceInfoListVO": [
                                {
                                    "displayName": "黄金增值服务金价",
                                    "categoryGroup": 2,
                                    "sortOrder": 3,
                                    "isEnabled": True,
                                    "isShowInFrontend": True,
                                    "todayDate": "2026-07-30",
                                    "goldPrice": 1188,
                                }
                            ],
                        },
                        {
                            "categoryName": "黄金回收服务",
                            "goldPriceInfoListVO": [
                                {
                                    "displayName": "黄金回收服务金价",
                                    "categoryGroup": 3,
                                    "sortOrder": 4,
                                    "isEnabled": True,
                                    "isShowInFrontend": True,
                                    "todayDate": "2026-07-30",
                                    "goldPrice": "879",
                                }
                            ],
                        },
                    ]
                },
            },
        )

    monkeypatch.setattr(zdf, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/zdf/default",
            "query_string": b"",
            "headers": [],
        }
    )

    route_data = await zdf.handle_route(request, no_cache=True)

    assert route_data.kind == "gold"
    assert route_data.total == 5
    assert all(isinstance(item, GoldItem) for item in route_data.data)
    assert route_data.data[0].sellPrice == 1262
    assert route_data.data[0].recyclePrice is None
    assert [item.id for item in route_data.data] == [
        "shipin",
        "gongyi-jintiao",
        "touzi-huangjin",
        "zengzhi",
        "huishou",
    ]
    assert route_data.data[1].title == "工艺金章金条类"
    assert route_data.data[2].sellPrice == 1068
    assert route_data.data[4].sellPrice is None
    assert route_data.data[4].recyclePrice == 879
    assert route_data.data[0].url == zdf.SOURCE_LINK
    assert route_data.data[0].mobileUrl is None
    assert "mobileUrl" not in route_data.data[0].model_dump(exclude_none=True)
    assert "hot" not in route_data.data[0].model_dump()
