from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zhihu-daily"

ROUTE_META: dict = {
    "name": "zhihu-daily",
    "title": "知乎日报",
    "description": "每天三次，每次七分钟",
    "link": "https://daily.zhihu.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://daily.zhihu.com/api/4/news/latest"
    result = await get(
        url=url,
        no_cache=no_cache,
        headers={
            "Referer": "https://daily.zhihu.com/api/4/news/latest",
            "Host": "daily.zhihu.com",
        },
    )
    stories = result.data.get("stories", [])
    items = [s for s in stories if s.get("type") == 0]
    data = [
        ListItem(
            id=v["id"],
            title=v["title"],
            cover=(v.get("images") or [None])[0],
            author=v.get("hint"),
            hot=None,
            timestamp=None,
            url=v.get("url", ""),
            mobileUrl=v.get("url", ""),
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="推荐榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
