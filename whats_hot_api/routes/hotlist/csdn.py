from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "csdn"

ROUTE_META: dict = {
    "name": "csdn",
    "title": "CSDN",
    "description": "专业开发者社区",
    "link": "https://www.csdn.net/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=30"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", [])
    data = [
        ListItem(
            id=v["productId"],
            title=v["articleTitle"],
            cover=(v.get("picList") or [None])[0],
            desc=None,
            author=v.get("nickName"),
            timestamp=get_time(v.get("period")),
            hot=int(v.get("hotRankScore", 0)),
            url=v["articleDetailUrl"],
            mobileUrl=v["articleDetailUrl"],
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="排行榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
