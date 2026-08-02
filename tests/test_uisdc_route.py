from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import uisdc
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_uisdc_parses_embedded_news_payload(monkeypatch):
    payload = [
        {
            "id": 677060,
            "time": 1784102400,
            "dubao": [
                {
                    "title": "AI design news",
                    "url": "",
                    "content": "新闻摘要。[[官网:https://example.com/news]]",
                    "tag": "设计工具",
                    "hot": "9.1",
                    "images": "|||https://example.com/cover.webp|",
                }
            ],
        }
    ]
    encoded = json.dumps(json.dumps(payload, ensure_ascii=False))
    html = f"<script>var uisdc_news = {encoded};</script>"

    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(uisdc, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/uisdc", "query_string": b"", "headers": []}
    )
    route_data = await uisdc.handle_route(request)

    assert route_data.total == 1
    item = route_data.data[0]
    assert item.id == "677060-1"
    assert item.hot == 91
    assert item.desc == "设计工具 · 新闻摘要。"
    assert item.cover == "https://example.com/cover.webp"
    assert item.url == "https://example.com/news"
