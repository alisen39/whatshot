from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.routes.newsflash import netease_news
from whats_hot_api.utils.http_client import RequestResult

SAMPLE = {
    "code": 200,
    "msg": "success",
    "data": {
        "list": [
            {
                "docid": "ABC123",
                "title": "First article",
                "url": "https://m.163.com/news/article/ABC123.html",
                "source": "网易号作者",
                "ptime": "2026-08-27 01:40:00",
                "imgsrc": "http://img.example/abc.jpg",
            },
            {
                "title": "Video without docid",
                "skipType": "video",
                "skipID": "VIDEO123",
                "vid": "VIDEO123",
                "url": "https://m.163.com/news/video/VIDEO123.html",
                "ptime": "2026-08-27 01:20:00",
            },
            {"title": "Unsupported card without document ID", "skipType": "special"},
            {
                "docid": "BADURL",
                "title": "Unsafe URL",
                "url": "javascript:alert(1)",
            },
            {
                "docid": "DEF456",
                "title": "Second article",
                "url": "https://m.163.com/news/article/DEF456.html",
                "publishTime": "2026-08-27 01:00:00",
            },
        ]
    },
}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/netease-news",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_netease_news_skips_non_article_rows(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T02:00:00+00:00", SAMPLE)

    monkeypatch.setattr(netease_news, "get", fake_get)
    result = await netease_news.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": netease_news.API_URL,
        "no_cache": True,
        "ttl": config.NEWSFLASH_CACHE_TTL,
    }
    assert result.kind == "newsflash"
    assert result.type == "最新内容"
    assert result.total == 3
    first = result.data[0]
    assert first.id == "ABC123"
    assert first.content == first.title == "First article"
    assert first.contentStatus == "summary"
    assert first.source == "网易号作者"
    assert first.timestamp == 1787766000000
    assert first.url == "https://m.163.com/news/article/ABC123.html"
    assert first.images == ["http://img.example/abc.jpg"]

    video = result.data[1]
    assert video.id == "VIDEO123"
    assert video.url == "https://m.163.com/news/video/VIDEO123.html"

    second = result.data[2]
    assert second.id == "DEF456"
    assert second.source == "网易新闻"
    assert second.timestamp == 1787763600000


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"code": 500}, "unsuccessful"),
        ({"code": 200, "data": {"list": []}}, "empty article list"),
        (
            {"code": 200, "data": {"list": [{"title": "no id"}]}},
            "no usable articles",
        ),
    ],
)
def test_netease_news_rejects_invalid_payload(payload, message):
    with pytest.raises(RuntimeError, match=message):
        netease_news._parse_items(payload)
