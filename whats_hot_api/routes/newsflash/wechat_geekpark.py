from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.article_feed import BACKFILL, fetch_article_feed, route_meta

ROUTE_NAME = "wechat-geekpark"
ROUTE_META: dict = route_meta(ROUTE_NAME)

__all__ = ["BACKFILL", "ROUTE_META", "ROUTE_NAME", "handle_route"]


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return await fetch_article_feed(ROUTE_NAME, no_cache)
