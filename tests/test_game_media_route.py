from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import game_media
from whats_hot_api.utils.http_client import RequestResult

RSS_SAMPLE = (
    "<?xml version=\"1.0\"?><rss><channel>"
    "<item><guid>https://www.gcores.com/articles/220062</guid><title>机核文章</title>"
    "<link>https://www.gcores.com/articles/220062</link></item>"
    "</channel></rss>"
)


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/game-media",
        "query_string": b"type=gcores-latest",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_gcores_feed_parsed_with_program_ua(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(game_media, "get", fake_get)
    result = await game_media.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://www.gcores.com/rss"
    # 如实程序 UA:阿里云 WAF 只对冒充浏览器的请求出挑战页
    assert captured["headers"]["User-Agent"].startswith("python-httpx/")
    assert result.type == "机核 · 全站最新（官方 RSS）"
    assert result.total == 1
    assert result.data[0].title == "机核文章"


@pytest.mark.asyncio
async def test_waf_challenge_page_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<script>aliyun_waf_aa challenge</script>" + "x" * 20000)

    monkeypatch.setattr(game_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="challenge"):
        await game_media.handle_route(_request(), no_cache=True)
