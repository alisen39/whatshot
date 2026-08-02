from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "netease-news"

ROUTE_META: dict = {
    "name": "netease-news",
    "title": "网易新闻",
    "link": "https://m.163.com/hot",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://m.163.com/fe/api/hot/news/flow"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", {}).get("list", [])
    data = [
        ListItem(
            id=v["docid"],
            title=v["title"],
            cover=v.get("imgsrc"),
            author=v.get("source"),
            hot=None,
            timestamp=get_time(v.get("ptime")),
            url=f"https://www.163.com/dy/article/{v['docid']}.html",
            mobileUrl=f"https://m.163.com/dy/article/{v['docid']}.html",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="热点榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
