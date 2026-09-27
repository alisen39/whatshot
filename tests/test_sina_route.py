from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import sina
from whats_hot_api.utils.http_client import RequestResult

FIXTURE_ITEMS = [
    {
        "base": {"base": {"uniqueId": "abc123", "url": "https://news.sina.cn/a1"}},
        "info": {"title": "标题一", "hotValue": "456.7万"},
    },
    {
        "base": {"base": {"uniqueId": "def456", "url": "https://news.sina.cn/a2"}},
        "info": {"title": "标题二", "hotValue": "123"},
    },
]


def _request(type_param: str = "all") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/sina",
            "query_string": f"type={type_param}".encode(),
            "headers": [],
        }
    )


def test_retired_mother_channel_is_not_a_declared_board():
    assert "mother" not in sina.type_map
    assert "mother" not in (sina.ROUTE_META["params"]["type"]["type"])


@pytest.mark.asyncio
async def test_parses_hotlist_items(monkeypatch):
    async def fake_get(url, **kwargs):
        assert "top_news_list-all" in url
        return RequestResult(
            False,
            "2026-09-14T00:00:00+00:00",
            {"status": 0, "data": {"hotList": FIXTURE_ITEMS}},
        )

    monkeypatch.setattr(sina, "get", fake_get)
    route_data = await sina.handle_route(_request("all"), no_cache=True)

    assert route_data.type == "新浪热榜"
    assert route_data.total == 2
    assert route_data.data[0].id == "abc123"
    assert route_data.data[0].title == "标题一"
    assert route_data.data[0].url == "https://news.sina.cn/a1"
    assert route_data.data[0].hot == 4567000


@pytest.mark.asyncio
async def test_retired_channel_envelope_raises_instead_of_keyerror(monkeypatch):
    async def fake_get(url, **kwargs):
        return RequestResult(
            False,
            "2026-09-14T00:00:00+00:00",
            {"status": -1, "msg": "empty data", "data": {}},
        )

    monkeypatch.setattr(sina, "get", fake_get)
    with pytest.raises(RuntimeError, match="no hotList"):
        await sina.handle_route(_request("all"), no_cache=True)
