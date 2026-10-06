from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import kuaishou_index
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/kuaishou-index",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_hot_rank_board_posts_rank_type_in_body(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", {
            "code": "200",
            "data": [
                {"keyword": "关键词一", "hotValue": 1234567, "poster": "http://img.ks/1.jpg"},
                {"keyword": "关键词二", "hotValue": 100, "poster": None},
            ],
        })

    monkeypatch.setattr(kuaishou_index, "post", fake_post)
    result = await kuaishou_index.handle_route(_request("useful"), no_cache=True)

    # rankType 只能放 JSON 体里;放 URL 参数返回 -101
    assert captured["url"] == "https://index.e.kuaishou.com/rest/index/list/hot-rank"
    assert captured["body"] == {"rankType": 5}
    assert captured["headers"]["Referer"].startswith("https://index.e.kuaishou.com/")
    assert result.type == "有用榜"
    item = result.data[0]
    assert item.id == "关键词一"
    assert item.hot == 1234567
    assert item.cover == "https://img.ks/1.jpg"  # http 升 https
    # 详情页 rankType 必须与所在榜一致,否则不在主榜的词显示"暂无该热点详情"
    assert "rankType=5" in result.data[1].url


@pytest.mark.asyncio
async def test_search_rising_board_uses_get(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://index.e.kuaishou.com/rest/index/list/search-rank"
        return RequestResult(False, "t", {"code": "200", "data": [{"keyword": "飙升词", "hotValue": 9}]})

    monkeypatch.setattr(kuaishou_index, "get", fake_get)
    result = await kuaishou_index.handle_route(_request("search-rising"), no_cache=True)
    assert result.type == "搜索飙升榜"
    assert "rankType=100" in result.data[0].url


@pytest.mark.asyncio
async def test_drama_board_items_come_from_tube_rank(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {
            "code": "200",
            "data": {
                "topRank": [],
                "mustRank": [{"tubeName": "短剧甲", "url": "https://www.kuaishou.com/short-video/3xabc?from=x",
                              "popularityValue": 777, "poster": "https://img.ks/p.jpg", "channelName": "都市", "onlineTime": 1790769600}],
            },
        })

    monkeypatch.setattr(kuaishou_index, "get", fake_get)
    result = await kuaishou_index.handle_route(_request("drama-must"), no_cache=True)

    assert result.type == "短剧必看榜"
    item = result.data[0]
    assert item.id == "3xabc"
    assert item.hot == 777
    assert item.desc == "都市"
    assert item.timestamp == 1790769600000


@pytest.mark.asyncio
async def test_empty_drama_must_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"code": "200", "data": {"topRank": [], "mustRank": []}})

    monkeypatch.setattr(kuaishou_index, "get", fake_get)

    with pytest.raises(RuntimeError, match="returned no items"):
        await kuaishou_index.handle_route(_request("drama-must"), no_cache=True)


@pytest.mark.asyncio
async def test_business_error_code_is_an_error(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"code": "100001", "message": "参数不合法"})

    monkeypatch.setattr(kuaishou_index, "post", fake_post)
    with pytest.raises(RuntimeError, match="100001"):
        await kuaishou_index.handle_route(_request("hot"), no_cache=True)


def test_removed_drama_hot_board_is_gone():
    assert "drama-hot" not in kuaishou_index.ROUTE_META["params"]["type"]["type"]
    assert len(kuaishou_index.type_map) == 7
