from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "36kr"

type_map: dict[str, str] = {
    "hot": "人气榜",
    "zonghe": "综合榜",
    "collect": "收藏榜",
}

_list_type_key: dict[str, str] = {
    "hot": "topList",
    "zonghe": "hotList",
    "collect": "collectList",
}

_API_URL = "https://gateway.36kr.com/api/mis/x/rank/list"

ROUTE_META: dict = {
    "name": "36kr",
    "title": "36氪",
    "params": {
        "type": {
            "name": "热榜分类",
            "type": type_map,
        },
    },
    "link": "https://36kr.com/hot-list/catalog",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    result = await post(
        _API_URL,
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        body={
            "partner_id": "web",
            "param": {
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
        raise ValueError("36kr rank API returned an unsuccessful response")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TypeError("36kr rank API returned an invalid data envelope")
    key = _list_type_key[type_param]
    items = data.get(key)
    if not isinstance(items, list):
        raise TypeError(f"36kr rank API returned an invalid {key}")
    if not items:
        raise ValueError(f"36kr rank API returned an empty {key}")
    hot_field = "statHot" if type_param == "hot" else "statCollect"
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["itemId"],
                title=v["widgetTitle"],
                cover=v.get("widgetImage"),
                author=v.get("authorName"),
                desc=v.get("summary") or None,
                timestamp=get_time(v.get("publishTime")),
                hot=v.get(hot_field) or None,
                url=f"https://www.36kr.com/p/{v['itemId']}",
                mobileUrl=f"https://m.36kr.com/p/{v['itemId']}",
            )
            for v in items
        ],
    }
