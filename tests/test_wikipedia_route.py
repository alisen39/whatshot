from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import wikipedia
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", wikipedia.type_map)
async def test_wikipedia_language_boards(monkeypatch, lang):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert f"https://{lang}.wikipedia.org/" in kwargs["url"]
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {"mostread": {"articles": [{
                "pageid": 123,
                "title": "Test_article",
                "normalizedtitle": "Test article",
                "description": "Article description",
                "views": 4567,
                "thumbnail": {"source": "https://example.com/cover.jpg"},
                "content_urls": {"desktop": {"page": f"https://{lang}.wikipedia.org/wiki/Test_article"}},
            }]}},
        )

    monkeypatch.setattr(wikipedia, "get", fake_get)
    request = Request({
        "type": "http", "method": "GET", "path": "/wikipedia",
        "query_string": f"type={lang}".encode(), "headers": [],
    })
    route_data = await wikipedia.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == wikipedia.type_map[lang]
    assert item.id == "123"
    assert item.title == "Test article"
    assert item.hot == 4567
    assert item.url == f"https://{lang}.wikipedia.org/wiki/Test_article"
