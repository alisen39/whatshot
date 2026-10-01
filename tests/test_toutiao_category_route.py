from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import toutiao_category
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/toutiao-category",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _board_card(category: str, items: list[dict]) -> dict:
    return {
        "cell_type": 800,
        "raw_data": {"board": [{"category": category, "hot_board_items": items}, {"category": "normal", "hot_board_items": []}]},
    }


def _payload(category: str, items: list[dict]) -> dict:
    return {"data": [{"content": json.dumps(_board_card(category, items), ensure_ascii=False)}]}


ITEMS = [{"id_str": "7300000000000000001", "title": "话题一"}, {"id_str": "7300000000000000002", "title": "话题二"}]


@pytest.mark.asyncio
async def test_category_board_is_parsed_from_hotspot_feed(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _payload("sports", ITEMS))

    monkeypatch.setattr(toutiao_category, "get", fake_get)
    result = await toutiao_category.handle_route(_request("sports"), no_cache=True)

    assert captured["url"] == "https://i-lq.snssdk.com/api/news/feed/v88/"
    assert captured["params"]["category"] == "news_hotspot"
    assert captured["params"]["update_version_code"] == "95007"
    assert captured["headers"]["User-Agent"].startswith("okhttp/")
    assert result.name == "toutiao-category"
    assert result.type == "体育榜"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "7300000000000000001"
    assert first.url == "https://www.toutiao.com/trending/7300000000000000001/"


@pytest.mark.asyncio
async def test_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="Unknown category"):
        await toutiao_category.handle_route(_request("nonsense"), no_cache=True)


@pytest.mark.asyncio
async def test_missing_board_card_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", _payload("finance", ITEMS))

    monkeypatch.setattr(toutiao_category, "get", fake_get)
    with pytest.raises(RuntimeError, match="no 'sports' board"):
        await toutiao_category.handle_route(_request("sports"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", {})

    monkeypatch.setattr(toutiao_category, "get", fake_get)
    with pytest.raises(RuntimeError, match="empty response"):
        await toutiao_category.handle_route(_request("sports"), no_cache=True)
