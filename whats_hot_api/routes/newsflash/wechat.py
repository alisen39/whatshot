from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.article_feed import (
    BACKFILL,
    WECHAT_FEEDS,
    WECHAT_META,
    WECHAT_ROUTE,
    fetch_wechat_feed,
)

ROUTE_NAME = WECHAT_ROUTE
ROUTE_META: dict = WECHAT_META

__all__ = ["BACKFILL", "ROUTE_META", "ROUTE_NAME", "handle_route"]


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await fetch_wechat_feed(request.query_params.get("type", next(iter(WECHAT_FEEDS))), no_cache)
