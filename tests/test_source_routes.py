from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import (
    bilibili,
    chongbuluo,
    kaopu,
    pcbeta,
)
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    })


def test_replaced_alias_routes_are_owned_by_native_route_types():
    assert "0" in bilibili.ROUTE_META["params"]["type"]["type"]
    assert {"hot", "latest"} <= set(chongbuluo.ROUTE_META["params"]["type"]["type"])
    assert "windows11" in pcbeta.ROUTE_META["params"]["type"]["type"]


@pytest.mark.asyncio
async def test_kaopu_native_route_maps_items(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert "kaopustorage.blob.core.windows.net" in kwargs["url"]
        return RequestResult(
            False,
            "kaopu-update",
            [
                {
                    "title": "靠谱新闻标题",
                    "description": "新闻摘要",
                    "publisher": "Source A",
                    "pub_date": "2026-07-06T08:00:00Z",
                    "link": "https://example.com/news",
                },
                {
                    "title": "过滤掉的财新",
                    "publisher": "财新",
                    "link": "https://example.com/blocked",
                },
            ],
        )

    monkeypatch.setattr(kaopu, "get", fake_get)

    route_data = await kaopu.handle_route(_request())

    assert route_data.name == "kaopu"
    assert len(route_data.data) == 1
    assert route_data.data[0].title == "靠谱新闻标题"
    assert route_data.data[0].author == "Source A"
