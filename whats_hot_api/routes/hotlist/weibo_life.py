from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-life"

ROUTE_META: dict = {
    "params": {"type": {"name": "榜单", "type": {"life": "生活榜"}}},
    "name": "weibo-life",
    "title": "微博生活榜",
    "description": "微博热搜生活分类榜",
    "link": "https://s.weibo.com/top/summary?cate=life",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("life", ROUTE_META, request, no_cache)
