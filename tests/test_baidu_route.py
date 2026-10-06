from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import baidu
from whats_hot_api.utils.http_client import RequestResult

S_DATA = (
    '<html><!--s-data:{"data":{"cards":[{"content":['
    '{"word":"民生话题","query":"民生话题","hotScore":"12345"},'
    '{"word":"第二条","hotScore":"88"}]}]}}--></html>'
)


def _request(tab: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/baidu",
        "query_string": f"type={tab}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(("tab", "label"), [("livelihood", "民生榜"), ("finance", "财经榜")])
async def test_extra_boards_parse_s_data(monkeypatch, tab, label):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", S_DATA)

    monkeypatch.setattr(baidu, "get", fake_get)
    result = await baidu.handle_route(_request(tab), no_cache=True)

    assert captured["url"] == f"https://top.baidu.com/board?tab={tab}"
    assert result.type == label
    assert result.total == 2
    first = result.data[0]
    assert first.title == "民生话题"
    assert first.hot == 12345
    assert first.url == "https://www.baidu.com/s?wd=%E6%B0%91%E7%94%9F%E8%AF%9D%E9%A2%98"
