from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qq-news"

ROUTE_META: dict = {
    "name": "qq-news",
    "title": "腾讯新闻",
    "link": "https://news.qq.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://r.inews.qq.com/gw/event/hot_ranking_list?page_size=50"
    result = await get(url=url, no_cache=no_cache)
    id_list = result.data.get("idlist", [])
    news_list = id_list[0].get("newslist", []) if id_list else []
    # Skip first item as in the TS source
    items = news_list[1:]
    data = [
        ListItem(
            id=v["id"],
            title=v["title"],
            desc=v.get("abstract"),
            cover=v.get("miniProShareImage"),
            author=v.get("source"),
            hot=v.get("hotEvent", {}).get("hotScore"),
            timestamp=get_time(v.get("timestamp")),
            url=f"https://new.qq.com/rain/a/{v['id']}",
            mobileUrl=f"https://view.inews.qq.com/k/{v['id']}",
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
