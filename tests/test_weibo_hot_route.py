from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import weibo
from whats_hot_api.utils.http_client import RequestResult


ROWS = [
    {
        "realpos": 1,
        "rank": 0,
        "word": "年轻人一定要对钱有概念",
        "word_scheme": "年轻人一定要对钱有概念",
        "num": 374284,
        "category": "情感",
        "label_name": "热",
        "onboard_time": 1784300362,
    },
    {
        "rank": 0,
        "word": "广告词",
        "num": 350000,
        "is_ad": 1,
    },
    {
        "realpos": 2,
        "rank": 1,
        "word": "功夫女足让韩国人破防了",
        "word_scheme": "#功夫女足让韩国人破防了#",
        "num": 308759,
        "category": "电影",
        "label_name": "热",
        "onboard_time": 1784303001,
    },
]


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/weibo/hot",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_weibo_uses_official_hot_band_and_excludes_ads(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://weibo.com/ajax/statuses/hot_band"
        assert kwargs["headers"]["Referer"] == "https://weibo.com/"
        return RequestResult(
            False,
            "2026-07-18T00:00:00+00:00",
            {"ok": 1, "data": {"band_list": ROWS}},
        )

    monkeypatch.setattr(weibo, "get", fake_get)
    route_data = await weibo.handle_route(_request())

    assert route_data.type == "热搜榜"
    assert route_data.total == 2
    assert [item.id for item in route_data.data] == [
        "年轻人一定要对钱有概念",
        "功夫女足让韩国人破防了",
    ]
    first = route_data.data[0]
    assert first.hot == 374284
    assert first.timestamp == 1784300362000
    assert first.desc is None
    assert first.url == (
        "https://s.weibo.com/weibo?"
        "q=%23%E5%B9%B4%E8%BD%BB%E4%BA%BA%E4%B8%80%E5%AE%9A%E8%A6%81"
        "%E5%AF%B9%E9%92%B1%E6%9C%89%E6%A6%82%E5%BF%B5%23"
    )
    assert first.mobileUrl == first.url


def test_weibo_parser_requires_contiguous_unique_ranked_topics():
    gap = [ROWS[0], {**ROWS[2], "realpos": 3}]
    duplicate = [ROWS[0], {**ROWS[2], "word": ROWS[0]["word"]}]

    assert weibo._parse_hot_band({"ok": 1, "data": {"band_list": gap}}) == []
    assert weibo._parse_hot_band({"ok": 1, "data": {"band_list": duplicate}}) == []


def test_weibo_parser_rejects_failed_or_malformed_payloads():
    assert weibo._parse_hot_band({"ok": 0, "data": {"band_list": ROWS}}) == []
    assert weibo._parse_hot_band({"ok": 1, "data": {"band_list": "bad"}}) == []
    assert weibo._parse_hot_band({"ok": 1, "data": {"band_list": [None]}}) == []
