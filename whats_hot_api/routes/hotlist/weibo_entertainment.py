from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-entertainment"

ROUTE_META: dict = {
    "name": "weibo-entertainment",
    "title": "微博文娱榜",
    "description": "微博热搜文娱分类榜",
    "link": "https://s.weibo.com/top/summary?cate=entrank",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("entertainment", ROUTE_META, request, no_cache)
