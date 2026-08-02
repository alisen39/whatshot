from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import caixin_data
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/caixin-data",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_caixin_data_maps_public_latest_items_and_skips_ads(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/api/dataplus/sjtPc/news")
        assert kwargs["params"]["pageSize"] == "100"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": {
                    "data": [
                        {"flag": "ad", "type": 2},
                        {
                            "title": "A股六月科技行情深化",
                            "summary": "预测经营质量、动量等因子表现更优",
                            "url": "https://database.caixin.com/2026-07-16/102464883.html?cxapp_link=true",
                            "tag": "量化观察",
                            "pic": "https://img.example/cover.jpg",
                            "time": 1_784_199_454,
                        },
                        {
                            "title": "沪指收盘失守3900点",
                            "url": "https://cxdata.caixin.com/AandH/?id=f38807a32cda4e5c9654ee67f0df05c8",
                            "tag": "大盘脉搏",
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(caixin_data, "get", fake_get)
    route_data = await caixin_data.handle_route(_request())

    assert route_data.kind == "newsflash"
    assert route_data.type == "内容精选"
    assert route_data.total == 2
    first, second = route_data.data
    assert first.id == "102464883"
    assert first.source == "量化观察"
    assert first.tags == ["量化观察"]
    assert first.images == ["https://img.example/cover.jpg"]
    assert first.timestamp == 1_784_199_454_000
    assert second.id == "f38807a32cda4e5c9654ee67f0df05c8"
    assert second.content == second.title


def test_caixin_data_fallback_id_is_stable():
    url = "https://example.com/latest/story"
    assert caixin_data._item_id(url) == caixin_data._item_id(url)
    assert len(caixin_data._item_id(url)) == 20
