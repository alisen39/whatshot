from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import kr36
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/36kr",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _entry(item_id: str, **fields) -> dict:
    return {
        "itemId": item_id,
        "widgetTitle": f"条目{item_id}",
        "widgetImage": "https://img.36krcdn.com/cover.jpg",
        "authorName": "作者",
        "summary": "摘要",
        "publishTime": 1793495335085,
        **fields,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "label", "list_key", "heat_field", "heat_value"),
    [
        ("hot", "人气榜", "topList", "statHot", "147.46"),
        ("zonghe", "综合榜", "hotList", "statCollect", 78),
        ("collect", "收藏榜", "collectList", "statCollect", 50),
    ],
)
async def test_current_boards_use_aggregate_rank_endpoint(
    monkeypatch, board_type, label, list_key, heat_field, heat_value
):
    captured = {}

    async def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            {"code": 0, "data": {list_key: [_entry("6001", **{heat_field: heat_value})]}},
        )

    monkeypatch.setattr(kr36, "post", fake_post)
    result = await kr36.handle_route(_request(board_type), no_cache=True)

    assert captured == {
        "url": "https://gateway.36kr.com/api/mis/x/rank/list",
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": {"partner_id": "web", "param": {"siteId": 1, "platformId": 2}},
        "no_cache": True,
        "cache_key": "https://gateway.36kr.com/api/mis/x/rank/list",
        "response_type": "json",
    }
    assert result.type == label
    assert result.total == 1
    item = result.data[0]
    assert item.hot == round(float(heat_value))
    assert item.url == "https://www.36kr.com/p/6001"
    assert item.mobileUrl == "https://m.36kr.com/p/6001"
    assert item.cover == "https://img.36krcdn.com/cover.jpg"
    assert item.author == "作者"
    assert item.desc == "摘要"
    assert item.timestamp == 1793495335085


@pytest.mark.asyncio
@pytest.mark.parametrize("board_type", ["video", "comment", "unknown"])
async def test_retired_or_unknown_board_is_rejected_before_fetch(monkeypatch, board_type):
    async def fail_post(*args, **kwargs):
        raise AssertionError("unsupported boards must not call the upstream")

    monkeypatch.setattr(kr36, "post", fail_post)
    with pytest.raises(ValueError, match="Unknown board"):
        await kr36.handle_route(_request(board_type), no_cache=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"code": 1, "data": {}}, "unsuccessful response"),
        ({"code": 0, "data": None}, "invalid data envelope"),
        ({"code": 0, "data": {"topList": None}}, "invalid topList"),
        ({"code": 0, "data": {"topList": []}}, "empty topList"),
    ],
)
async def test_invalid_rank_envelope_is_not_a_success(monkeypatch, payload, message):
    async def fake_post(*args, **kwargs):
        return RequestResult(False, "t", payload)

    monkeypatch.setattr(kr36, "post", fake_post)
    with pytest.raises((TypeError, ValueError), match=message):
        await kr36.handle_route(_request("hot"), no_cache=True)


def test_route_metadata_matches_current_official_board_set():
    assert kr36.ROUTE_META["link"] == "https://36kr.com/hot-list/catalog"
    assert kr36.type_map == {"hot": "人气榜", "zonghe": "综合榜", "collect": "收藏榜"}
