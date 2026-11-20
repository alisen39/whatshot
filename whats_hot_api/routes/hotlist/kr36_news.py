from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = '36kr-news'
SOURCE_LINK = 'https://36kr.com/'
_API_URL = "https://gateway.36kr.com/api/mis/nav/ifm/subNav/flow"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": '36Kr Latest',
    "description": 'Chinese startup and technology business headlines.',
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"latest": "Latest"},
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Latest",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await post(
        _API_URL,
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        body={
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
        no_cache=no_cache,
        cache_key=_API_URL,
        response_type="json",
    )
    payload = result.data
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ValueError("36kr flow API returned an unsuccessful response")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("itemList"), list):
        raise TypeError("36kr flow API returned an invalid payload")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [_list_item(v["templateMaterial"]) for v in data["itemList"]],
    }


def _list_item(material: dict) -> ListItem:
    # id, url and mobileUrl are all the article URL, matching the board's stored source_item_id.
    url = f"https://www.36kr.com/p/{material['itemId']}"
    return ListItem(
        id=url,
        title=material["widgetTitle"],
        url=url,
        mobileUrl=url,
        cover=material.get("widgetImage"),
        desc=material.get("summary") or None,
        timestamp=get_time(material.get("publishTime")),
    )
