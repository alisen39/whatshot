from __future__ import annotations

import time

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "36kr"

type_map: dict[str, str] = {
    "hot": "人气榜",
    "video": "视频榜",
    "comment": "热议榜",
    "collect": "收藏榜",
}

_list_type_key: dict[str, str] = {
    "hot": "hotRankList",
    "video": "videoList",
    "comment": "remarkList",
    "collect": "collectList",
}

ROUTE_META: dict = {
    "name": "36kr",
    "title": "36氪",
    "params": {
        "type": {
            "name": "热榜分类",
            "type": type_map,
        },
    },
    "link": "https://m.36kr.com/hot-list-m",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "人气榜"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://gateway.36kr.com/api/mis/nav/home/nav/rank/{type_param}"
    result = await post(
        url,
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        body={
            "partner_id": "wap",
            "param": {
                "siteId": 1,
                "platformId": 2,
            },
            "timestamp": int(time.time() * 1000),
        },
        no_cache=no_cache,
        cache_key=url,
    )
    key = _list_type_key.get(type_param, "hotRankList")
    items = result.data["data"][key]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["itemId"],
                title=v["templateMaterial"]["widgetTitle"],
                cover=v["templateMaterial"].get("widgetImage"),
                author=v["templateMaterial"].get("authorName"),
                desc=v["templateMaterial"].get("summary") or None,
                timestamp=get_time(v.get("publishTime")),
                hot=v["templateMaterial"].get("statCollect") or None,
                url=f"https://www.36kr.com/p/{v['itemId']}",
                mobileUrl=f"https://m.36kr.com/p/{v['itemId']}",
            )
            for v in items
        ],
    }
