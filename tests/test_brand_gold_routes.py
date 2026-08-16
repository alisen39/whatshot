from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.models import GoldItem
from whats_hot_api.routes.gold import (
    baoqing,
    caibai,
    china_gold,
    chow_taifook_hk,
    chowsangsang,
    emperor_jewellery,
    laofengxiang_gd,
    lukfook,
    zhouliufu,
)
from whats_hot_api.utils.http_client import RequestResult


def _request(route_name: str, board_type: str = "hot") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/{route_name}/hot",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _result(data: object) -> RequestResult:
    return RequestResult(False, "2026-08-16T00:00:00+00:00", data)


def _assert_gold_response(route_data, expected_name: str) -> None:
    assert route_data.name == expected_name
    assert route_data.kind == "gold"
    assert route_data.total == len(route_data.data)
    assert route_data.data
    assert all(isinstance(item, GoldItem) for item in route_data.data)
    assert all(item.quotes for item in route_data.data)


@pytest.mark.asyncio
async def test_china_gold_maps_retail_buyback_and_benchmark(monkeypatch):
    async def fake_post(**kwargs):
        assert kwargs["body"] is None if "body" in kwargs else True
        return _result(
            {
                "code": 200,
                "data": {
                    "accessories": "1303.00",
                    "sel": "957.50",
                    "buy": "938.50",
                    "cur": "941.50",
                },
            }
        )

    monkeypatch.setattr(china_gold, "post", fake_post)
    route_data = await china_gold.handle_route(_request(china_gold.ROUTE_NAME), True)

    _assert_gold_response(route_data, "china-gold")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "investment-gold",
        "base-gold-price",
    ]
    assert route_data.data[1].sellPrice == 957.5
    assert route_data.data[1].recyclePrice == 938.5
    assert route_data.data[2].quotes[0].quoteType == "benchmark"
    assert route_data.data[0].timestamp is None


@pytest.mark.asyncio
async def test_lukfook_forces_mainland_currency_and_unit(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["headers"] == {"lang": "sc"}
        return _result(
            {
                "status": 1,
                "data": {
                    "record_date": "2026-08-10 9:34:00",
                    "group": [
                        {"GoldS": "1306", "GoldT": "1108"},
                        {"pts": "678", "ptc": "542"},
                        {"InvestmentS": "1146", "InvestmentB": "927"},
                        {"GoldPiece": "1296"},
                    ],
                },
            }
        )

    monkeypatch.setattr(lukfook, "get", fake_get)
    route_data = await lukfook.handle_route(_request(lukfook.ROUTE_NAME), True)

    _assert_gold_response(route_data, "lukfook")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "platinum-950",
        "investment-gold",
    ]
    assert route_data.data[2].model_dump()["recyclePrice"] == 927
    assert route_data.data[0].timestamp == 1786325640000


@pytest.mark.asyncio
async def test_lukfook_maps_hong_kong_native_gram_and_tael_quotes(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["headers"] == {"lang": "tc"}
        return _result(
            {
                "status": 1,
                "data": {
                    "rmb_buyprice": "115.5",
                    "record_date": "2026-08-10 16:49:33",
                    "group": [
                        {
                            "GoldS": "1319.5",
                            "GoldB": "1054",
                            "GoldT": "1094.1",
                            "GoldT*": "1084.1",
                            "GoldTS": "49388",
                            "GoldTB": "39438",
                            "GoldTT": "40938",
                            "GoldTT*": "40564",
                        },
                        {
                            "InvestmentS": "1246",
                            "InvestmentB": "1053.7",
                            "InvestmentT": "1064.4",
                            "InvestmentT*": "1059.4",
                            "InvestmentTS": "46640",
                            "InvestmentTB": "39427",
                            "InvestmentTT": "39827",
                            "InvestmentTT*": "39640",
                        },
                        {
                            "PlatinumS": "561",
                            "PlatinumB": "403.4",
                            "PlatinumT": "411.4",
                            "PlatinumTS": "20991",
                            "PlatinumTB": "15090",
                            "PlatinumTT": "15389",
                        },
                        {
                            "GoldPieceS": "1179.5",
                            "GoldPieceB": "1066.3",
                            "GoldPieceT": "1074.3",
                            "GoldPieceTS": "44154",
                            "GoldPieceTB": "39916",
                            "GoldPieceTT": "40215",
                        },
                    ],
                },
            }
        )

    monkeypatch.setattr(lukfook, "get", fake_get)
    route_data = await lukfook.handle_route(
        _request(lukfook.ROUTE_NAME, "hong-kong"), True
    )

    _assert_gold_response(route_data, "lukfook")
    assert route_data.type == "中国香港 · HKD"
    assert len(route_data.data) == 4
    assert sum(len(item.quotes) for item in route_data.data) == 28
    gold = route_data.data[0]
    assert gold.sellPrice is None
    assert [quote.unit for quote in gold.quotes].count("gram") == 4
    assert [quote.unit for quote in gold.quotes].count("tael") == 4
    assert gold.quotes[0].model_dump()["price"] == 1319.5
    assert all(
        quote.currency == "HKD" for item in route_data.data for quote in item.quotes
    )


@pytest.mark.asyncio
async def test_caibai_keeps_supported_gold_retail_rows(monkeypatch):
    async def fake_post(**kwargs):
        assert isinstance(kwargs["body"], str)
        assert "SQLBuilderItem" in kwargs["body"]
        return _result(
            {
                "JsonResult": True,
                "JsonData": [
                    {
                        "ROW": [
                            {
                                "FKIND_NAME": "足金饰品",
                                "FPRICE_BASE": "1288.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "足金999饰品",
                                "FPRICE_BASE": "1290.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "足金999饰品金条",
                                "FPRICE_BASE": "1120.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "菜百投资基础金价",
                                "FPRICE_BASE": "942.70 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "铂金950饰品",
                                "FPRICE_BASE": "615.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                        ]
                    }
                ],
            }
        )

    monkeypatch.setattr(caibai, "post", fake_post)
    route_data = await caibai.handle_route(_request(caibai.ROUTE_NAME), True)

    _assert_gold_response(route_data, "caibai")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "gold-999-jewellery",
        "gold-999-bar",
    ]


@pytest.mark.asyncio
async def test_chowsangsang_pairs_sell_and_third_party_buyback(monkeypatch):
    rows = [
        {
            "region": "CHN",
            "type": "G_JW_SELL",
            "price": "1307",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:00.000+08:00",
        },
        {
            "region": "CHN",
            "type": "G_JW_CNTPTBUY",
            "price": "909",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T19:12:33.800+08:00",
        },
        {
            "region": "CHN",
            "type": "G_INGOT_SELL",
            "price": "1147",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:07.000+08:00",
        },
        {
            "region": "CHN",
            "type": "G_INGOT_CNTPTBUY",
            "price": "909",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T19:12:33.800+08:00",
        },
        {
            "region": "CHN",
            "type": "G_JW_GPEXCH",
            "price": "1099",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:00.000+08:00",
        },
    ]

    async def fake_get(**kwargs):
        return _result(f"<script>{json.dumps(rows, ensure_ascii=False)}</script>")

    monkeypatch.setattr(chowsangsang, "get", fake_get)
    route_data = await chowsangsang.handle_route(
        _request(chowsangsang.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "chowsangsang")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "investment-gold",
    ]
    assert route_data.data[0].sellPrice == 1307
    assert route_data.data[0].recyclePrice == 909
    assert "第三方回收方" in (route_data.data[0].desc or "")


@pytest.mark.asyncio
async def test_laofengxiang_keeps_gold_sell_rows_and_normalizes_date(monkeypatch):
    body = """
    <span id="labTitle">2026年08月10日</span>
    <span id="labContent">1302</span>
    <span id="labContent_1">1108</span>
    <span id="labContent3">1159</span>
    <span id="labContent1">1159</span>
    <span id="labContent2">650</span>
    """

    async def fake_get(**kwargs):
        return _result(body)

    monkeypatch.setattr(laofengxiang_gd, "get", fake_get)
    route_data = await laofengxiang_gd.handle_route(
        _request(laofengxiang_gd.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "laofengxiang-gd")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "investment-gold",
        "jewellery-gold-bar",
        "platinum-950",
    ]
    assert all(item.timestamp == 1786291200000 for item in route_data.data)
    assert [quote.quoteType for quote in route_data.data[0].quotes] == [
        "retail_sell",
        "exchange",
    ]


@pytest.mark.asyncio
async def test_zhouliufu_deduplicates_responsive_markup(monkeypatch):
    body = """
    <div class="update-time">更新时间：2026-08-08 10:20:00</div>
    <div class="gold-item"><span class="label">品类</span><span class="value">零售指导价</span></div>
    <div class="gold-item"><span class="label">足金999‰</span><span class="value">1303</span></div>
    <div class="gold-item"><span class="label">足金999.9‰</span><span class="value">1313</span></div>
    <div class="gold-item"><span class="label">工艺金</span><span class="value">1143</span></div>
    <div class="gold-item"><span class="label">足铂999‰</span><span class="value">698</span></div>
    <div class="gold-item"><span class="label">足金999‰</span><span class="value">1303</span></div>
    """

    async def fake_get(**kwargs):
        return _result(body)

    monkeypatch.setattr(zhouliufu, "get", fake_get)
    route_data = await zhouliufu.handle_route(_request(zhouliufu.ROUTE_NAME), True)

    _assert_gold_response(route_data, "zhouliufu")
    assert [item.id for item in route_data.data] == [
        "gold-999",
        "gold-9999",
        "craft-gold",
    ]


@pytest.mark.asyncio
async def test_baoqing_drops_client_generated_time(monkeypatch):
    body = """
    <div class="jinList_li">
      <div class="jinList_li_Ri_text1">
        <div class="jinList_li_Ri_t_le">足金（饰品、工艺品类）</div>
        <div class="jinList_li_Ri_t_ri"><span>1248</span>元/克</div>
      </div>
      <div class="jinList_li_Ri_text1">
        <div class="jinList_li_Ri_t_le">5G<br>黄金摆件</div>
        <div class="jinList_li_Ri_t_ri"><span>1188</span>元/克</div>
      </div>
    </div>
    """

    async def fake_get(**kwargs):
        assert "Mozilla/5.0" in kwargs["headers"]["User-Agent"]
        return _result(body)

    monkeypatch.setattr(baoqing, "get", fake_get)
    route_data = await baoqing.handle_route(_request(baoqing.ROUTE_NAME), True)

    _assert_gold_response(route_data, "baoqing")
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "gold-5g-ornament",
    ]
    assert all(item.timestamp is None for item in route_data.data)


@pytest.mark.asyncio
async def test_chow_taifook_hk_keeps_native_units(monkeypatch):
    payload = {
        "Updated_Time": "2026-08-10 15:06:03",
        "Gold_Sell": "49388",
        "Gold_Sell_g": "1319.5",
        "Gold_Buy": "39438",
        "Gold_Buy_g": "1054",
        "Redemption_Price": "40938",
        "Redemption_Price_g": "1094.1",
    }
    body = (
        '<input class="gold-price-data d-none" value="'
        + json.dumps(payload).replace('"', "&quot;")
        + '">'
    )

    async def fake_get(**kwargs):
        return _result(body)

    monkeypatch.setattr(chow_taifook_hk, "get", fake_get)
    route_data = await chow_taifook_hk.handle_route(
        _request(chow_taifook_hk.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "chow-taifook-hk")
    assert route_data.type == "中国香港 · HKD"
    assert route_data.data[0].sellPrice is None
    assert {(quote.currency, quote.unit) for quote in route_data.data[0].quotes} == {
        ("HKD", "gram"),
        ("HKD", "tael"),
    }


@pytest.mark.asyncio
async def test_emperor_jewellery_marks_missing_source_time(monkeypatch):
    async def fake_get(**kwargs):
        return _result(
            "Selling Price: HK$ 49,380.00 /tael — Buying Price: HK$ 39,450.00 /tael"
        )

    monkeypatch.setattr(emperor_jewellery, "get", fake_get)
    route_data = await emperor_jewellery.handle_route(
        _request(emperor_jewellery.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "emperor-jewellery")
    item = route_data.data[0]
    assert item.sellPrice is None
    assert [quote.model_dump()["price"] for quote in item.quotes] == [49380, 39450]
    assert all(not quote.sourceQuoteTimeTrusted for quote in item.quotes)
