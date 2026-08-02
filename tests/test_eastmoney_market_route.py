from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import eastmoney_market
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/eastmoney-market",
            "query_string": query,
            "headers": [],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_field", "expected_order", "expected_label"),
    [
        (b"type=gainers", "f3", "1", "A股涨幅榜"),
        (b"type=losers", "f3", "0", "A股跌幅榜"),
        (b"type=main-inflow", "f62", "1", "主力净流入榜"),
    ],
)
async def test_eastmoney_market_uses_official_board_sort(
    monkeypatch,
    query,
    expected_field,
    expected_order,
    expected_label,
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/api/qt/clist/get")
        assert kwargs["params"]["fid"] == expected_field
        assert kwargs["params"]["po"] == expected_order
        assert kwargs["params"]["fs"] == "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": {
                    "diff": [
                        {
                            "f12": "600276",
                            "f13": 1,
                            "f14": "恒瑞医药",
                            "f2": 57.5,
                            "f3": 4.89,
                            "f6": 12_345_678_900,
                            "f62": 1_157_377_728,
                            "f184": 10.53,
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(_request(query))
    item = route_data.data[0]

    assert route_data.kind == "hotlist"
    assert route_data.type == expected_label
    assert item.id == "1.600276"
    assert item.title == "恒瑞医药"
    assert item.author == "600276"
    assert item.url == "https://quote.eastmoney.com/unify/r/1.600276"
    assert "涨跌幅 +4.89%" in item.desc
    assert "主力净流入 +11.57 亿元" in item.desc


@pytest.mark.asyncio
async def test_eastmoney_market_falls_back_to_gainers(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["fid"] == "f3"
        assert kwargs["params"]["po"] == "1"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"data": {"diff": []}})

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(_request(b"type=unknown"))
    assert route_data.type == "A股涨幅榜"
    assert route_data.data == []


@pytest.mark.asyncio
async def test_eastmoney_market_supports_market_and_metric_combinations(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["fid"] == "f6"
        assert kwargs["params"]["po"] == "1"
        assert kwargs["params"]["fs"] == "m:116+t:3,m:116+t:4,m:116+t:1,m:116+t:2"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"data": {"diff": []}})

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(_request(b"type=hk-turnover"))
    assert route_data.type == "港股 · 成交额榜"


def test_eastmoney_market_declares_complete_public_rank_matrix():
    assert len(eastmoney_market.type_map) == 74
    assert "us-rate" in eastmoney_market.type_map
    assert "bj-a-volume" in eastmoney_market.type_map
    assert eastmoney_market.type_map["discussion-stock"]["name"] == "24H 讨论热股"
    assert eastmoney_market.type_map["hot-topic"]["name"] == "热门话题"
    assert eastmoney_market.type_map["dragon-tiger-30d"]["name"] == "龙虎榜 · 近30日"
    assert eastmoney_market.type_map["board-change-count"]["name"] == "板块异动 · 次数榜"
    assert eastmoney_market.type_map["concept-flow-10d"]["name"] == "概念板块资金 · 10日"
    assert eastmoney_market.type_map["department-return-1y"]["cycle"] == "04"
    assert eastmoney_market.type_map["active-department-30d"]["date_field"] == "STARTDATE30"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_id", "expected_hot"),
    [
        ("discussion-stock", "1.600733", 31_313),
        ("hot-topic", "10730", 14_420_000),
    ],
)
async def test_eastmoney_market_parses_caifuhao_rankings(
    monkeypatch, board_type, expected_id, expected_hot
):
    html = """
    <div id="hot_stock"><ul class="list_side"><li class="item">
      <div class="right"><span>31313</span></div>
      <div class="left"><a href="/hot/stock/1/600733/600733">北汽蓝谷[600733]</a></div>
    </li></ul></div>
    <div class="hot_topic"><ul class="topic_list"><li class="item">
      <div class="img"><img src="//img.example/topic.png"></div>
      <div class="detail">
        <p class="title"><a href="https://gubatopic.eastmoney.com/topic_v3.html?htid=10730">热门话题</a></p>
        <p class="desc">话题摘要</p>
        <p class="info">阅读 <span title="1442万">1442万</span> | 讨论 <span title="6万">6万</span></p>
      </div>
    </li></ul></div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://caifuhao.eastmoney.com/hot"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(f"type={board_type}".encode())
    )

    assert route_data.data[0].id == expected_id
    assert route_data.data[0].hot == expected_hot
    if board_type == "discussion-stock":
        assert route_data.data[0].author == "600733"
        assert route_data.data[0].url.endswith("/hot/stock/1/600733/600733")
    else:
        assert route_data.data[0].cover == "https://img.example/topic.png"
        assert "讨论 6万" in route_data.data[0].desc


@pytest.mark.asyncio
async def test_eastmoney_market_parses_dragon_tiger_period(monkeypatch):
    calls = 0

    async def fake_get(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        if calls == 1:
            assert kwargs["url"].endswith("/stock/tradedetail.html")
            return RequestResult(
                False,
                "2026-07-16T00:00:00+00:00",
                """
                <ul class="day_type">
                  <li data-value="1" date="2026-07-16"></li>
                  <li data-value="5" date="2026-07-10"></li>
                </ul>
                """,
            )
        assert kwargs["params"]["reportName"] == "RPT_DAILYBILLBOARD_DETAILSNEW"
        assert kwargs["params"]["filter"] == "(TRADE_DATE<='2026-07-16')(TRADE_DATE>='2026-07-10')"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "result": {
                    "data": [
                        {
                            "SECURITY_CODE": "688008",
                            "SECURITY_NAME_ABBR": "澜起科技",
                            "TRADE_DATE": "2026-07-16 00:00:00",
                            "CHANGE_RATE": -16.2,
                            "BILLBOARD_NET_AMT": 1_323_264_854.23,
                            "TURNOVERRATE": 7.5,
                            "EXPLANATION": "日收盘价格跌幅达到15%",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(b"type=dragon-tiger-5d")
    )

    assert route_data.type == "龙虎榜 · 近5日"
    assert route_data.data[0].id == "2026-07-16:688008"
    assert route_data.data[0].hot == 1_323_264_854
    assert "净买额 +13.23 亿元" in route_data.data[0].desc
    assert route_data.data[0].url.endswith("/lhb,2026-07-16,688008.html")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_first", "expected_hot"),
    [
        ("board-change-count", "BK_COUNT", 500),
        ("board-change-rate", "BK_RATE", 650),
        ("board-change-funds", "BK_FUNDS", 9_000_000_000_000),
    ],
)
async def test_eastmoney_market_sorts_board_changes(
    monkeypatch, board_type, expected_first, expected_hot
):
    rows = [
        {"c": "BK_COUNT", "m": 90, "n": "次数板块", "ct": 500, "u": 1.2, "zjl": 100, "ms": {"n": "股票甲", "t": 8201}},
        {"c": "BK_RATE", "m": 90, "n": "涨幅板块", "ct": 2, "u": 6.5, "zjl": 200, "ms": {"n": "股票乙", "t": 8193}},
        {"c": "BK_FUNDS", "m": 90, "n": "资金板块", "ct": 3, "u": 2.1, "zjl": 900_000_000, "ms": {"n": "股票丙", "t": 8219}},
    ]

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/getAllBKChanges")
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"data": {"allbk": rows}})

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(f"type={board_type}".encode())
    )

    assert route_data.data[0].id == expected_first
    assert route_data.data[0].hot == expected_hot
    assert "最大异动股" in route_data.data[0].desc
    if board_type == "board-change-funds":
        assert "主力资金 +90000.00 亿元" in route_data.data[0].desc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_filter", "expected_field", "leader_field"),
    [
        ("concept-flow-today", "m:90+t:3", "f62", "f204"),
        ("concept-flow-5d", "m:90+t:3", "f164", "f257"),
        ("concept-flow-10d", "m:90+t:3", "f174", "f260"),
        ("industry-flow-today", "m:90+s:4", "f62", "f204"),
        ("industry-flow-5d", "m:90+s:4", "f164", "f257"),
        ("industry-flow-10d", "m:90+s:4", "f174", "f260"),
    ],
)
async def test_eastmoney_market_parses_sector_flow_rankings(
    monkeypatch, board_type, expected_filter, expected_field, leader_field
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["fs"] == expected_filter
        assert kwargs["params"]["fid"] == expected_field
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": {
                    "diff": [
                        {
                            "f12": "BK0737",
                            "f14": "软件开发",
                            expected_field: 1_234_567_890,
                            "f3": 2.5,
                            "f109": 3.5,
                            "f160": 4.5,
                            "f184": 10.1,
                            "f165": 11.1,
                            "f175": 12.1,
                            leader_field: "领涨科技",
                            {"f204": "f205", "f257": "f258", "f260": "f261"}[
                                leader_field
                            ]: "600001",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(f"type={board_type}".encode())
    )

    assert route_data.data[0].id == "90.BK0737"
    assert route_data.data[0].hot == 1_234_567_890
    assert "领涨股 领涨科技（600001）" in route_data.data[0].desc
    assert route_data.data[0].url.endswith("/bkzj/BK0737.html")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_cycle"),
    [
        ("department-return-1m", "01"),
        ("department-return-3m", "02"),
        ("department-return-6m", "03"),
        ("department-return-1y", "04"),
    ],
)
async def test_eastmoney_market_parses_department_return_rankings(
    monkeypatch, board_type, expected_cycle
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["reportName"] == "RPT_RATEDEPT_RETURNT_RANKING"
        assert kwargs["params"]["filter"] == f'(STATISTICSCYCLE="{expected_cycle}")'
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "result": {
                    "data": [
                        {
                            "OPERATEDEPT_CODE": "10634757",
                            "OPERATEDEPT_NAME": "深股通专用",
                            "TOTAL_BUYER_SALESTIMES_1DAY": 1252,
                            "AVERAGE_INCREASE_1DAY": 0.08,
                            "RISE_PROBABILITY_1DAY": 51.2,
                            "AVERAGE_INCREASE_3DAY": 0.32,
                            "RISE_PROBABILITY_3DAY": 53.4,
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(f"type={board_type}".encode())
    )

    assert route_data.data[0].id == "10634757"
    assert route_data.data[0].hot == 1252
    assert "后1日均涨 +0.08% / 上涨概率 51.20%" in route_data.data[0].desc
    assert route_data.data[0].url.endswith("/stock/lhb/yyb/10634757.html")


@pytest.mark.asyncio
async def test_eastmoney_market_uses_official_active_department_period(monkeypatch):
    calls = 0

    async def fake_get(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        if calls == 1:
            assert kwargs["params"]["reportName"] == "RPT_ORGANIZATION_DATE"
            return RequestResult(
                False,
                "2026-07-16T00:00:00+00:00",
                {"result": {"data": [{"NEWDATE": "2026-07-16 00:00:00", "STARTDATE5": "2026-07-10 00:00:00"}]}},
            )
        assert kwargs["params"]["reportName"] == "RPT_OPERATEDEPT_ACTIVE"
        assert kwargs["params"]["filter"] == "(ONLIST_DATE>='2026-07-10')"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "result": {
                    "data": [
                        {
                            "OPERATEDEPT_CODE": "10135341",
                            "OPERATEDEPT_NAME": "中信证券股份有限公司上海分公司",
                            "ONLIST_DATE": "2026-07-16 00:00:00",
                            "TOTAL_NETAMT": 1_276_058_926.62,
                            "TOTAL_BUYAMT": 1_711_753_369.32,
                            "TOTAL_SELLAMT": 435_694_442.7,
                            "BUYER_APPEAR_NUM": 17,
                            "SELLER_APPEAR_NUM": 13,
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney_market, "get", fake_get)
    route_data = await eastmoney_market.handle_route(
        _request(b"type=active-department-5d")
    )

    item = route_data.data[0]
    assert item.id == "2026-07-16:10135341"
    assert item.hot == 1_276_058_926
    assert "净买额 +12.76 亿元" in item.desc
    assert "买方 17 股 / 卖方 13 股" in item.desc
