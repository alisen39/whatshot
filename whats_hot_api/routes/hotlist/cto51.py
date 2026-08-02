from __future__ import annotations

import time

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.cto51 import get_token, sign

ROUTE_NAME = "51cto"

ROUTE_META: dict = {
    "name": "51cto",
    "title": "51CTO",
    "link": "https://www.51cto.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="推荐榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://api-media.51cto.com/index/index/recommend"
    params = {
        "page": 1,
        "page_size": 50,
        "limit_time": 0,
        "name_en": "",
    }
    timestamp = int(time.time() * 1000)
    token = await get_token()
    result = await get(
        url=url,
        params={
            **params,
            "timestamp": timestamp,
            "token": token,
            "sign": sign("index/index/recommend", dict(params), timestamp, token),
        },
        no_cache=no_cache,
        cache_key=url,
    )
    items = result.data.get("data", {}).get("data", {}).get("list", [])
    data = [
        ListItem(
            id=v.get("source_id", ""),
            title=v.get("title", ""),
            cover=v.get("cover") or None,
            desc=v.get("abstract") or None,
            timestamp=get_time(v.get("pubdate", "")),
            url=v.get("url", ""),
            mobileUrl=v.get("url", ""),
        )
        for v in items
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
