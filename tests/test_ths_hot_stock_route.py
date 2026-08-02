from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import ths_10jqka
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_ths_hot_stock_is_hotlist_board(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {
            "stock_type": "a",
            "type": "day",
            "list_type": "normal",
        }
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": {
                    "stock_list": [
                        {
                            "code": "002185",
                            "name": "华天科技",
                            "rate": "65735876",
                            "rise_and_fall": -10.0078,
                            "tag": {
                                "concept_tag": ["国家大基金持股", "先进封装"],
                                "popularity_tag": "持续上榜",
                            },
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(ths_10jqka, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ths-10jqka",
            "query_string": b"type=hot-stock",
            "headers": [],
        }
    )
    route_data = await ths_10jqka.handle_route(request)

    assert route_data.kind == "hotlist"
    assert route_data.type == "热股榜"
    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "002185"
    assert item.hot == 65735876
    assert item.desc == "涨跌幅：-10.01% · 持续上榜 · 概念：国家大基金持股、先进封装"
    assert item.url == "https://stockpage.10jqka.com.cn/002185/"


@pytest.mark.asyncio
async def test_ths_industry_flow_today_is_hotlist_board(monkeypatch):
    page_one = """
    <span class="page_info">1/2</span><table><tbody><tr>
      <td>1</td>
      <td><a href="http://q.10jqka.com.cn/thshy/detail/code/881274/">影视院线</a></td>
      <td>1285.4</td><td>4.96%</td><td>33.64</td><td>27.80</td>
      <td>5.84</td><td>20</td><td>华智数媒</td><td>13.94%</td><td>6.05</td>
    </tr></tbody></table>
    """
    page_two = """
    <table><tbody><tr>
      <td>51</td>
      <td><a href="http://q.10jqka.com.cn/thshy/detail/code/881159/">其他社会服务</a></td>
      <td>18261</td><td>-0.74%</td><td>4.10</td><td>5.20</td>
      <td>-1.10</td><td>31</td><td>科锐国际</td><td>-2.00%</td><td>16.20</td>
    </tr></tbody></table>
    """
    calls = 0

    async def fake_get(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        assert kwargs["headers"]["hexin-v"] == "test-token"
        assert kwargs["response_type"] == "text"
        return RequestResult(
            calls == 2,
            f"2026-07-16T00:00:0{calls}+00:00",
            page_one if calls == 1 else page_two,
        )

    monkeypatch.setattr(ths_10jqka, "generate_hexin_v", lambda: "test-token")
    monkeypatch.setattr(ths_10jqka, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ths-10jqka",
            "query_string": b"type=industry-flow-today",
            "headers": [],
        }
    )
    route_data = await ths_10jqka.handle_route(request)

    assert calls == 2
    assert route_data.kind == "hotlist"
    assert route_data.type == "行业资金流 · 即时"
    assert route_data.total == 2
    assert route_data.fromCache is False
    assert route_data.updateTime == "2026-07-16T00:00:02+00:00"
    first = route_data.data[0]
    assert first.id == "881274"
    assert first.title == "影视院线"
    assert first.hot == 584_000_000
    assert first.desc == (
        "涨跌幅 +4.96%；流入 33.64 亿元；流出 27.80 亿元；"
        "20 家公司；领涨股 华智数媒（+13.94%）"
    )
    assert first.url == "https://q.10jqka.com.cn/thshy/detail/code/881274/"


@pytest.mark.asyncio
async def test_ths_industry_flow_3d_maps_historical_columns(monkeypatch):
    html = """
    <span class="page_info">1/1</span><table><tbody><tr>
      <td>1</td>
      <td><a href="http://q.10jqka.com.cn/thshy/detail/code/881143/">医药商业</a></td>
      <td>32</td><td>4639.53</td><td>9.60%</td>
      <td>12.13</td><td>11.08</td><td>1.05</td>
    </tr></tbody></table>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/funds/hyzjl/board/3/ajax/1/")
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            html,
        )

    monkeypatch.setattr(ths_10jqka, "generate_hexin_v", lambda: "test-token")
    monkeypatch.setattr(ths_10jqka, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ths-10jqka",
            "query_string": b"type=industry-flow-3d",
            "headers": [],
        }
    )
    route_data = await ths_10jqka.handle_route(request)

    assert route_data.kind == "hotlist"
    assert route_data.type == "行业资金流 · 3日"
    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "881143"
    assert item.title == "医药商业"
    assert item.hot == 105_000_000
    assert item.desc == (
        "涨跌幅 +9.60%；流入 12.13 亿元；流出 11.08 亿元；32 家公司"
    )


@pytest.mark.asyncio
async def test_ths_concept_flow_today_maps_concept_code(monkeypatch):
    html = """
    <span class="page_info">1/1</span><table><tbody><tr>
      <td>1</td>
      <td><a href="http://q.10jqka.com.cn/gn/detail/code/309023/">高压氧舱</a></td>
      <td>1024.8</td><td>2.84%</td><td>0.12</td><td>0.10</td>
      <td>0.02</td><td>5</td><td>创新医疗</td><td>4.20%</td><td>9.30</td>
    </tr></tbody></table>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith(
            "/funds/gnzjl/field/tradezdf/order/desc/ajax/1/"
        )
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            html,
        )

    monkeypatch.setattr(ths_10jqka, "generate_hexin_v", lambda: "test-token")
    monkeypatch.setattr(ths_10jqka, "get", fake_get)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ths-10jqka",
            "query_string": b"type=concept-flow-today",
            "headers": [],
        }
    )
    route_data = await ths_10jqka.handle_route(request)

    assert route_data.kind == "hotlist"
    assert route_data.type == "概念资金流 · 即时"
    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "309023"
    assert item.title == "高压氧舱"
    assert item.hot == 2_000_000
    assert item.url == "https://q.10jqka.com.cn/gn/detail/code/309023/"
