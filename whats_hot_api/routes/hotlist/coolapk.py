from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.coolapk import gen_headers

ROUTE_NAME = "coolapk"

ROUTE_META: dict = {
    "name": "coolapk",
    "title": "酷安",
    "link": "https://www.coolapk.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://api.coolapk.com/v6/page/dataList?url=/feed/statList?cacheExpires=300&statType=day&sortField=detailnum&title=今日热门&title=今日热门&subTitle=&page=1"
    result = await get(
        url=url,
        no_cache=no_cache,
        headers=gen_headers(),
    )
    items = result.data.get("data", [])
    data = [
        ListItem(
            id=v.get("id", ""),
            title=v.get("message", ""),
            cover=v.get("tpic") or None,
            author=v.get("username") or None,
            desc=v.get("ttitle") or None,
            url=v.get("shareUrl", ""),
            mobileUrl=v.get("shareUrl", ""),
        )
        for v in items
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
