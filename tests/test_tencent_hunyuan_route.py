from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.routes.newsflash import tencent_hunyuan
from whats_hot_api.utils.http_client import RequestResult

SAMPLE = {
    "code": 0,
    "msg": "success",
    "data": {
        "totalNum": 2,
        "list": [
            {
                "id": 100091,
                "title": "From LR to ELR",
                "desc": "Effective-learning-rate research summary.",
                "author": "Pretrain Team",
                "displayPublishTime": 1786377600,
                "customUrl": "elr",
            },
            {
                "id": 100041,
                "title": "Hy-MT2 released",
                "desc": "",
                "author": "",
                "displayPublishTime": 1779346800,
                "customUrl": "",
            },
        ],
    },
}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tencent-hunyuan",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_tencent_hunyuan_uses_official_api_and_maps_newsflash(monkeypatch):
    captured = {}

    async def fake_post(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-08-27T02:00:00+00:00", SAMPLE)

    monkeypatch.setattr(tencent_hunyuan, "post", fake_post)
    result = await tencent_hunyuan.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": tencent_hunyuan.API_URL,
        "headers": {"accept-language": "zh"},
        "body": {"pageNum": 1, "pageSize": 30},
        "no_cache": True,
        "ttl": config.NEWSFLASH_CACHE_TTL,
    }
    assert result.kind == "newsflash"
    assert result.type == "研究与发布"
    assert result.total == 2
    assert result.updateTime == "2026-08-27T02:00:00+00:00"

    first = result.data[0]
    assert first.id == "100091"
    assert first.title == "From LR to ELR"
    assert first.content == "Effective-learning-rate research summary."
    assert first.summary == "Effective-learning-rate research summary."
    assert first.contentStatus == "summary"
    assert first.source == "Pretrain Team"
    assert first.timestamp == 1786377600000
    assert first.url == "https://hunyuan.tencent.com/research/elr"
    assert first.mobileUrl == first.url

    second = result.data[1]
    assert second.content == second.title
    assert second.summary is None
    assert second.source == "腾讯混元"
    assert second.url == "https://hunyuan.tencent.com/research/100041"


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"code": 400}, "unsuccessful"),
        ({"code": 0, "data": {"list": []}}, "empty article list"),
        (
            {"code": 0, "data": {"list": [{"id": 1, "title": ""}]}},
            "no usable articles",
        ),
    ],
)
def test_tencent_hunyuan_rejects_invalid_payloads(payload, message):
    with pytest.raises(RuntimeError, match=message):
        tencent_hunyuan._parse_items(payload)


def test_tencent_hunyuan_rejects_unsafe_custom_slug():
    row = {"customUrl": "https://evil.example/item"}

    assert (
        tencent_hunyuan._detail_url(row, "100091")
        == "https://hunyuan.tencent.com/research/100091"
    )
