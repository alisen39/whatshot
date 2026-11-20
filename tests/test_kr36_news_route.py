from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import kr36_news
from whats_hot_api.utils.http_client import RequestResult

# Trimmed from a gateway subNav/flow response recorded on 2026-11-21.
FLOW_RESPONSE = {
    "code": 0,
    "data": {
        "itemList": [
            {
                "itemId": 4077952913298306,
                "itemType": 10,
                "templateMaterial": {
                    "itemId": 4077952913298306,
                    "templateType": 1,
                    "widgetImage": "https://img.36krcdn.com/hsossms/20261120/v2_29bdbe73f9dc406086e51ef314a03b88@000000@ai_oswg1045780oswg2048oswg2048_img_000~tplv-1marlgjv7f-ai-v3:600:400:600:400:q70.jpg",
                    "publishTime": 1795181842435,
                    "widgetTitle": "金价罕见大跌，原因找到了；未来怎么走，机构观点两极分化，大摩预计明年四季度能涨到5250美元；专家称预计下个月考验3070美元",
                    "summary": "金价罕见大跌，机构对其后续走势观点分化。",
                    "authorName": "36氪的朋友们",
                    "navName": "财经",
                },
                "route": "detail_article?itemId=4077952913298306",
                "siteId": 1,
            },
            {
                "itemId": 4077960501008008,
                "itemType": 10,
                "templateMaterial": {
                    "itemId": 4077960501008008,
                    "templateType": 1,
                    "widgetImage": "https://img.36krcdn.com/hsossms/20261120/v2_108b18841f504150bdecb530c54ea4b9@46958@ai_oswg658400oswg1053oswg495_img_png~tplv-1marlgjv7f-ai-v3:600:400:600:400:q70.jpg",
                    "publishTime": 1795181673104,
                    "widgetTitle": "从“刷分”打到“补缝”，机器人新竞赛升温",
                    "summary": "技术有突破，落地缺接口",
                    "authorName": "机器最前线",
                    "navName": "科技",
                },
                "route": "detail_article?itemId=4077960501008008",
                "siteId": 1,
            },
        ],
        "keywordList": ["36氪", "创投"],
        "hasNextPage": 1,
    },
}


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/36kr-news",
        "query_string": b"type=latest",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_latest_reads_gateway_flow(monkeypatch):
    captured = {}

    async def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return RequestResult(False, "2026-11-21T03:00:00+00:00", FLOW_RESPONSE)

    monkeypatch.setattr(kr36_news, "post", fake_post)
    result = await kr36_news.handle_route(_request(), no_cache=True)

    assert captured == {
        "url": "https://gateway.36kr.com/api/mis/nav/ifm/subNav/flow",
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": {
            "partner_id": "web",
            "param": {
                "subnavType": 1,
                "subnavNick": "web_news",
                "pageSize": 30,
                "pageEvent": 0,
                "pageCallback": "",
                "siteId": 1,
                "platformId": 2,
            },
        },
        "no_cache": True,
        "cache_key": "https://gateway.36kr.com/api/mis/nav/ifm/subNav/flow",
        "response_type": "json",
    }
    assert result.name == "36kr-news"
    assert result.type == "Latest"
    assert result.total == 2
    assert result.fromCache is False
    assert result.updateTime == "2026-11-21T03:00:00+00:00"
    # Same item fields and link format as the samples stored before the RSSHub outage.
    assert [item.model_dump(exclude_none=True) for item in result.data] == [
        {
            "id": "https://www.36kr.com/p/4077952913298306",
            "title": "金价罕见大跌，原因找到了；未来怎么走，机构观点两极分化，大摩预计明年四季度能涨到5250美元；专家称预计下个月考验3070美元",
            "url": "https://www.36kr.com/p/4077952913298306",
            "mobileUrl": "https://www.36kr.com/p/4077952913298306",
            "cover": "https://img.36krcdn.com/hsossms/20261120/v2_29bdbe73f9dc406086e51ef314a03b88@000000@ai_oswg1045780oswg2048oswg2048_img_000~tplv-1marlgjv7f-ai-v3:600:400:600:400:q70.jpg",
            "desc": "金价罕见大跌，机构对其后续走势观点分化。",
            "timestamp": 1795181842435,
        },
        {
            "id": "https://www.36kr.com/p/4077960501008008",
            "title": "从“刷分”打到“补缝”，机器人新竞赛升温",
            "url": "https://www.36kr.com/p/4077960501008008",
            "mobileUrl": "https://www.36kr.com/p/4077960501008008",
            "cover": "https://img.36krcdn.com/hsossms/20261120/v2_108b18841f504150bdecb530c54ea4b9@46958@ai_oswg658400oswg1053oswg495_img_png~tplv-1marlgjv7f-ai-v3:600:400:600:400:q70.jpg",
            "desc": "技术有突破，落地缺接口",
            "timestamp": 1795181673104,
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"code": 40001, "msg": "error"}, ValueError),
        ("<html>verify</html>", ValueError),
        ({"code": 0, "data": None}, TypeError),
        ({"code": 0, "data": {"itemList": None}}, TypeError),
        ({"code": 0, "data": {"itemList": [{"itemId": 1, "itemType": 10}]}}, KeyError),
    ],
)
async def test_invalid_flow_response_is_an_error(monkeypatch, payload, error):
    async def fake_post(*args, **kwargs):
        return RequestResult(False, "t", payload)

    monkeypatch.setattr(kr36_news, "post", fake_post)
    with pytest.raises(error):
        await kr36_news.handle_route(_request(), no_cache=True)
