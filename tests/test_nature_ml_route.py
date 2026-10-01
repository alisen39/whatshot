from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nature_ml
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = (
    "<?xml version=\"1.0\"?><rss><channel>"
    "<item><guid>https://www.nature.com/articles/s41586-026-1</guid>"
    "<title>ML paper</title><link>https://www.nature.com/articles/s41586-026-1</link>"
    "<pubDate>Wed, 30 Sep 2026 00:00:00 GMT</pubDate></item>"
    "</channel></rss>"
)


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/nature-ml",
        "query_string": b"type=ml",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_subject_feed_is_parsed(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(nature_ml, "get", fake_get)
    result = await nature_ml.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://www.nature.com/subjects/machine-learning.rss"
    assert result.name == "nature-ml"
    assert result.total == 1
    assert result.data[0].title == "ML paper"
    assert result.data[0].timestamp == 1790726400000  # 只精确到日(00:00 UTC)


@pytest.mark.asyncio
async def test_challenge_page_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>idp cookie check</html>")

    monkeypatch.setattr(nature_ml, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await nature_ml.handle_route(_request(), no_cache=True)
