from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-acg"

ROUTE_META: dict = {
    "name": "weibo-acg",
    "title": "微博ACG榜",
    "description": "微博热搜ACG分类榜",
    "link": "https://s.weibo.com/top/summary?cate=game",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("acg", ROUTE_META, request, no_cache)
