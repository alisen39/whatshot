from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import gov_policy
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_gov_policy_latest_documents(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {
            "t": "zhengcelibrary_gw",
            "sort": "publishDate",
            "sortType": "1",
            "pageSize": "30",
            "pageNum": "0",
        }
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {
            "searchVO": {"listVO": [{
                "id": "26337033",
                "title": "国务院办公厅关于转发<em>行动方案</em>的通知",
                "url": "https://www.gov.cn/zhengce/zhengceku/202607/content.htm",
                "puborg": "国务院办公厅",
                "pubtime": 1784019600000,
                "pcode": "国办函〔2026〕65号",
                "childtype": "城乡建设、环境保护",
                "summary": "政策摘要",
            }]}
        })

    monkeypatch.setattr(gov_policy, "get", fake_get)
    request = Request({
        "type": "http", "method": "GET", "path": "/gov-policy",
        "query_string": b"", "headers": [],
    })
    route_data = await gov_policy.handle_route(request)

    item = route_data.data[0]
    assert route_data.type == "最新政策"
    assert item.id == "26337033"
    assert item.title == "国务院办公厅关于转发 行动方案 的通知"
    assert item.author == "国务院办公厅"
    assert "国办函〔2026〕65号" in item.desc
    assert item.url.startswith("https://www.gov.cn/")
