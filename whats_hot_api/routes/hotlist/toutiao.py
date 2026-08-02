from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "toutiao"

ROUTE_META: dict = {
    "name": "toutiao",
    "title": "今日头条",
    "link": "https://www.toutiao.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", [])
    data = [
        ListItem(
            id=v["ClusterIdStr"],
            title=v["Title"],
            cover=v.get("Image", {}).get("url"),
            timestamp=get_time(v["ClusterIdStr"]),
            hot=int(v.get("HotValue", 0)),
            url=f"https://www.toutiao.com/trending/{v['ClusterIdStr']}/",
            mobileUrl=f"https://api.toutiaoapi.com/feoffline/amos_land/new/html/main/index.html?topic_id={v['ClusterIdStr']}",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
