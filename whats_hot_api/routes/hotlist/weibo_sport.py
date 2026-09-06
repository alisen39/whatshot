from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-sport"

ROUTE_META: dict = {
    "params": {"type": {"name": "榜单", "type": {"sport": "体育榜"}}},
    "name": "weibo-sport",
    "title": "微博体育榜",
    "description": "微博热搜体育分类榜",
    "link": "https://s.weibo.com/top/summary?cate=sport",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("sport", ROUTE_META, request, no_cache)
