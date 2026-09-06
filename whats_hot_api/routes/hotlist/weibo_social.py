from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist._weibo_categories import handle_category

ROUTE_NAME = "weibo-social"

ROUTE_META: dict = {
    "params": {"type": {"name": "榜单", "type": {"social": "社会榜"}}},
    "name": "weibo-social",
    "title": "微博社会榜",
    "description": "微博热搜社会分类榜",
    "link": "https://s.weibo.com/top/summary?cate=socialevent",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await handle_category("social", ROUTE_META, request, no_cache)
