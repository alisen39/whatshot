from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.models import GoldItem
from whats_hot_api.routes.gold import (
    baoqing,
    beijing_rtj,
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
async def test_beijing_rtj_maps_market_and_jewellery_quotes(monkeypatch):
    async def fake_post(**kwargs):
        assert kwargs["url"].endswith("/admin/get_price5.php")
        assert kwargs["response_type"] == "text"
        assert kwargs["ttl"] == 30
        assert kwargs["headers"]["Content-Type"] == (
            "application/x-www-form-urlencoded"
        )
        return _result(
            "price,944.5,948.5,14.4,14.65,373.5,377,270.5,272,0,0,"
            "942.14,703.65,352,261,12.24,08:00:00"
        )

    monkeypatch.setattr(beijing_rtj, "post", fake_post)
    route_data = await beijing_rtj.handle_route(_request(beijing_rtj.ROUTE_NAME), True)

    _assert_gold_response(route_data, "beijing-rtj")
    assert route_data.type == "贵金属实时行情 · CNY/克"
    assert [item.id for item in route_data.data] == [
        "market-gold",
        "market-silver",
        "market-platinum",
        "market-palladium",
        "jewellery-pure-gold",
        "jewellery-18k-gold",
        "jewellery-pt950",
        "jewellery-pd990",
        "jewellery-ag925",
    ]
    assert route_data.data[0].sellPrice == 948.5
    assert route_data.data[0].recyclePrice == 944.5
    assert route_data.data[3].metal == "palladium"
    assert route_data.data[3].quotes[0].label == "回购价"
    assert route_data.data[0].mobileUrl == beijing_rtj.MOBILE_LINK
    assert all(
        quote.sourceQuoteTime == "2026-08-16T08:00:00+08:00"
        and quote.sourceQuoteTimeTrusted
        for item in route_data.data
        for quote in item.quotes
    )


def test_beijing_rtj_only_trusts_nearby_time_of_day():
    assert (
        beijing_rtj._source_quote_time("23:59:30", "2026-08-16T16:00:00+00:00")
        == "2026-08-16T23:59:30+08:00"
    )
    assert (
        beijing_rtj._source_quote_time("12:00:00", "2026-08-16T16:00:00+00:00") is None
    )


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
    assert route_data.link == "https://www.lukfook.com/tc/page/goldprice"
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
                                "FKIND_NAME": "铂金950饰品",
                                "FPRICE_BASE": "615.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "铂金990饰品",
                                "FPRICE_BASE": "620.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "足铂999饰品",
                                "FPRICE_BASE": "625.00 元/克",
                                "FNEWTIME": "2026-08-10 18:23:05",
                            },
                            {
                                "FKIND_NAME": "菜百投资基础金价",
                                "FPRICE_BASE": "942.70 元/克",
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
        "platinum-950-jewellery",
        "platinum-990-jewellery",
        "platinum-999-jewellery",
        "investment-base-gold",
    ]
    assert route_data.data[-1].quotes[0].quoteType == "benchmark"
    assert all(item.timestamp == 1786357385000 for item in route_data.data)


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
        {
            "region": "CHN",
            "type": "G_RFINGOT_SELL",
            "price": "1147",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:02.000+08:00",
        },
        {
            "region": "CHN",
            "type": "PT950_JW_SELL",
            "price": "678",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:05.000+08:00",
        },
        {
            "region": "CHN",
            "type": "PT950_JW_GPEXCH",
            "price": "542",
            "currencyCode": "RMB",
            "weightUnit": "GM",
            "lastUpdateDate": "2026-08-10T09:30:05.000+08:00",
        },
    ]

    request_kwargs = {}

    async def fake_get(**kwargs):
        request_kwargs.update(kwargs)
        return _result(f"<script>{json.dumps(rows, ensure_ascii=False)}</script>")

    monkeypatch.setattr(chowsangsang, "get", fake_get)
    route_data = await chowsangsang.handle_route(
        _request(chowsangsang.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "chowsangsang")
    assert request_kwargs["headers"]["Referer"] == "https://cn.chowsangsang.com/"
    assert "Mozilla/5.0" in request_kwargs["headers"]["User-Agent"]
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "investment-gold",
        "gold-button",
        "platinum-950",
    ]
    assert route_data.data[0].sellPrice == 1307
    assert route_data.data[0].recyclePrice == 909
    assert "第三方回收方" in (route_data.data[0].desc or "")
    assert route_data.data[2].sellPrice == 1147
    assert [quote.quoteType for quote in route_data.data[3].quotes] == [
        "retail_sell",
        "exchange",
    ]


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
    <div class="gold-item"><span class="label">足铂</span><span class="value">688</span></div>
    <div class="gold-item"><span class="label">铂Pt950</span><span class="value">678</span></div>
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
        "platinum-999",
        "platinum",
        "platinum-950",
    ]
    assert all(item.metal == "platinum" for item in route_data.data[3:])


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
    assert chow_taifook_hk.ROUTE_META["params"]["type"]["type"] == {
        "hong-kong": "中国香港 · HKD"
    }
    payload = {
        "Updated_Time": "2026-08-10 15:06:03",
        "Gold_Sell": "49388",
        "Gold_Sell_g": "1319.5",
        "Gold_Buy": "39438",
        "Gold_Buy_g": "1054",
        "Redemption_Price": "40938",
        "Redemption_Price_g": "1094.1",
        "Jewellery_Redemption_Price": "40564",
        "Jewellery_Redemption_Price_g": "1084.1",
        "Gold_Pellet_Sell": "44154",
        "Gold_Pellet_Sell_g": "1179.5",
        "Gold_Pellet_Buy": "39916",
        "Gold_Pellet_Buy_g": "1066.3",
        "Gold_Pellet_Redemption_Price": "40215",
        "Gold_Pellet_Redemption_Price_g": "1074.3",
        "Platinum": "15090",
        "Platinum_g": "403.4",
        "Platinum_Redemption_Price": "15389",
        "Platinum_Redemption_Price_g": "411.4",
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
    assert [item.id for item in route_data.data] == [
        "gold-jewellery",
        "gold-pellet",
        "platinum",
    ]
    assert route_data.data[0].sellPrice is None
    assert {(quote.currency, quote.unit) for quote in route_data.data[0].quotes} == {
        ("HKD", "gram"),
        ("HKD", "tael"),
    }
    assert len(route_data.data[0].quotes) == 8
    assert sum(len(item.quotes) for item in route_data.data) == 18
    assert [quote.label for quote in route_data.data[0].quotes[4:]] == [
        "饰金换金价",
        "饰金换金价",
        "饰金换珠宝价",
        "饰金换珠宝价",
    ]
    assert route_data.data[1].quotes[-2].label == "金粒换货价"
    assert [quote.quoteType for quote in route_data.data[2].quotes] == [
        "buyback",
        "buyback",
        "exchange",
        "exchange",
    ]
    assert route_data.data[2].quotes[-1].label == "足铂金换货价"


@pytest.mark.asyncio
async def test_emperor_jewellery_parses_all_rows_and_source_time(monkeypatch):
    request_kwargs = {}

    async def fake_get(**kwargs):
        request_kwargs.update(kwargs)
        return _result(
            """
            <section class="gold-price-table">
              <div class="gold-table-desktop"><div class="body">
                <div class="row"><span class="name">足金飾品</span><span class="type">(兩)</span><span class="sell-price">49,380.00</span><span class="buy-price">39,450.00</span></div>
                <div class="row"><span class="name">足金金粒</span><span class="type">(兩)</span><span class="sell-price">43,840.00</span><span class="buy-price">39,690.00</span></div>
                <div class="row"><span class="name">足金金條</span><span class="type">(兩)</span><span class="sell-price">43,840.00</span><span class="buy-price">39,690.00</span></div>
                <div class="row"><span class="name">足鉑金首飾</span><span class="type">(兩)</span><span class="sell-price">20,670.00</span><span class="buy-price">14,990.00</span></div>
                <div class="row"><span class="name">黃鉑金首飾</span><span class="type">(兩)</span><span class="sell-price">34,910.00</span><span class="buy-price">27,240.00</span></div>
              </div></div>
              <p class="last-updated">最後更新時間 :2026/08/10 15:20:00</p>
            </section>
            """
        )

    monkeypatch.setattr(emperor_jewellery, "get", fake_get)
    route_data = await emperor_jewellery.handle_route(
        _request(emperor_jewellery.ROUTE_NAME), True
    )

    _assert_gold_response(route_data, "emperor-jewellery")
    assert [item.id for item in route_data.data] == [
        "gold-ornaments",
        "gold-pellet",
        "gold-bars",
        "platinum-990-ornaments",
        "gold-platinum-ornaments",
    ]
    assert [item.title for item in route_data.data] == [
        "足金飾品",
        "足金金粒",
        "足金金條",
        "足鉑金首飾",
        "黃鉑金首飾",
    ]
    assert request_kwargs["url"] == emperor_jewellery.SOURCE_LINK
    assert request_kwargs["headers"]["Accept-Language"] == "zh-HK,zh;q=0.9"
    assert all(item.url == emperor_jewellery.SOURCE_LINK for item in route_data.data)
    assert all(len(item.quotes) == 2 for item in route_data.data)
    assert all(item.timestamp == 1786346400000 for item in route_data.data)
    assert all(
        quote.sourceQuoteTimeTrusted
        for item in route_data.data
        for quote in item.quotes
    )
