from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-technology"

ROUTE_META: dict = {
    "params": {"type": {"name": "榜单", "type": {"technology": "科技榜"}}},
    "name": "weibo-technology",
    "title": "微博科技榜",
    "description": "微博热搜科技分类榜",
    "link": "https://s.weibo.com/top/summary?cate=tech",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("technology", ROUTE_META, request, no_cache)
