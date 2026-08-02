from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import NewsFlashItem
from whats_hot_api.routes.newsflash import xuangubao
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/xuangubao",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_xuangubao_maps_public_reports_as_reports(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {
            "limit": "20",
            "tag_ids": "",
            "category_ids": "",
        }
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "code": 20000,
                "data": {
                    "items": [
                        {
                            "id": 17690,
                            "title": "机器人零部件景气度拐点将至",
                            "summary": "<p>供应商产能逐步提升，关注核心零部件公司。</p>",
                            "route": "https://xuangutong.com.cn/ts/report/17690",
                            "published_at": 1784116948,
                            "tags": [{"name": "机器人"}],
                            "organizations": [{"name": "某证券"}],
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(xuangubao, "get", fake_get)

    route_data = await xuangubao.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "研报"
    assert isinstance(item, NewsFlashItem)
    assert item.content == "供应商产能逐步提升，关注核心零部件公司。"
    assert item.contentStatus == "summary"
    assert item.source == "某证券"
    assert item.tags == ["机器人"]
    assert item.timestamp == 1784116948000
    assert item.url == "https://xuangutong.com.cn/ts/report/17690"
