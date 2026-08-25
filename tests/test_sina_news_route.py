from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import sina_news
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/sina-news/8",
        "query_string": b"type=8",
        "headers": [],
    })


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "5689192",
        "title": "Valid finance story",
        "media": "新浪财经",
        "top_num": "1,234",
        "create_date": "2026-08-25",
        "create_time": "02:32:04",
        "url": "https://finance.sina.com.cn/example.shtml",
    }
    row.update(overrides)
    return row


def test_sina_news_skips_invalid_required_fields_without_losing_valid_rows():
    rows = [
        _row(),
        _row(id="5689191", title=False),
        _row(id="", title="Missing id"),
        _row(id="5689190", title="Bad URL", url="javascript:alert(1)"),
        "not-an-object",
    ]

    items = sina_news._build_items(rows)

    assert len(items) == 1
    assert items[0].id == "5689192"
    assert items[0].title == "Valid finance story"
    assert items[0].author == "新浪财经"
    assert items[0].hot == 1234
    assert items[0].timestamp == 1787596324000


@pytest.mark.asyncio
async def test_sina_news_incident_payload_returns_remaining_valid_rows(monkeypatch):
    payload = "var data = " + json.dumps(
        {"data": [_row(), _row(id="5689191", title=False)]},
        ensure_ascii=False,
    ) + ";"

    async def fake_get(*args, **kwargs):
        assert kwargs["response_type"] == "text"
        assert "top_cat=finance_0_suda" in args[0]
        return RequestResult(False, "2026-08-25T15:00:00+00:00", payload)

    monkeypatch.setattr(sina_news, "get", fake_get)
    result = await sina_news.handle_route(_request(), no_cache=True)

    assert result.type == "财经新闻"
    assert result.total == 1
    assert [item.id for item in result.data] == ["5689192"]
    assert result.updateTime == "2026-08-25T15:00:00+00:00"
