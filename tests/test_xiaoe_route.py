from __future__ import annotations

from copy import deepcopy

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import xiaoe
from whats_hot_api.utils.http_client import RequestResult


def _row(item_id: int = 6413, **overrides: object) -> dict:
    row = {
        "id": item_id,
        "img_url": "https://example.com/xiaoe.png",
        "title": "批改拖节奏？小鹅通上线 AI 智能批改",
        "time": "2026-06-18 18:36:10",
        "summary": "小鹅通 AI 智能批改上线，帮助商家高效做好交付履约",
        "news_link": f"/moreNews/articleDetail-{item_id}.html",
    }
    row.update(overrides)
    return row


def _payload(*rows: dict, total: int | None = None) -> dict:
    row_list = list(rows)
    count = len(row_list) if total is None else total
    return {
        "code": 0,
        "message": "success",
        "data": {
            "list": row_list,
            "pagination": {
                "current_page": 1,
                "page_size": "50",
                "total": count,
                "total_pages": (count + 49) // 50,
            },
        },
    }


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/xiaoe", "query_string": b"", "headers": []}
    )


@pytest.mark.asyncio
async def test_xiaoe_fetches_official_growth_articles(monkeypatch):
    second = _row(
        6412,
        title="社区团购为什么要做私域带货？",
        time="2026-06-15 17:48:31",
        news_link="/moreNews/articleDetail-6412.html",
    )

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://sem.xiaoe-tech.com/extendRead_v2/1.0.0"
        assert kwargs["params"] == {
            "page": 1,
            "page_size": 50,
            "search_type": 1,
            "pinyin": "",
        }
        assert kwargs["cache_key"] == "xiaoe:more-news:latest:50"
        return RequestResult(False, "2026-07-18T00:00:00+00:00", _payload(_row(), second))

    monkeypatch.setattr(xiaoe, "get", fake_get)
    result = await xiaoe.handle_route(_request(), True)

    assert result.name == "xiaoe"
    assert result.type == "增长干货"
    assert result.total == 2
    assert [item.id for item in result.data] == ["6413", "6412"]
    assert result.data[0].author == "小鹅通"
    assert result.data[0].timestamp == 1781778970000
    assert result.data[0].url == (
        "https://sem.xiaoe-tech.com/moreNews/articleDetail-6413.html"
    )
    assert result.data[0].cover == "https://example.com/xiaoe.png"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "bad"),
        ("title", ""),
        ("time", "2026/06/18"),
        ("news_link", "/moreNews/articleDetail-9999.html"),
        ("img_url", "http://example.com/x.png"),
    ],
)
def test_xiaoe_parser_rejects_invalid_article_identity(field, value):
    assert xiaoe._parse_response(_payload(_row(**{field: value}))) == []


def test_xiaoe_parser_rejects_duplicates_and_wrong_order():
    duplicate_id = _row(title="Another title")
    duplicate_title = _row(
        6412,
        news_link="/moreNews/articleDetail-6412.html",
        time="2026-06-17 00:00:00",
    )
    ascending = _row(
        6412,
        title="Newer second row",
        news_link="/moreNews/articleDetail-6412.html",
        time="2026-06-19 00:00:00",
    )

    assert xiaoe._parse_response(_payload(_row(), duplicate_id)) == []
    assert xiaoe._parse_response(_payload(_row(), duplicate_title)) == []
    assert xiaoe._parse_response(_payload(_row(), ascending)) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(code=1),
        lambda value: value["data"].update(list=[]),
        lambda value: value["data"]["pagination"].update(current_page=2),
        lambda value: value["data"]["pagination"].update(page_size=15),
        lambda value: value["data"]["pagination"].update(total=0),
        lambda value: value["data"]["pagination"].update(total_pages=99),
    ],
)
def test_xiaoe_parser_rejects_malformed_response_contract(mutation):
    payload = deepcopy(_payload(_row(), total=627))
    mutation(payload)
    assert xiaoe._parse_response(payload) == []
