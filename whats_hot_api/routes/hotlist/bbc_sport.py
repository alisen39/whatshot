from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bbc-sport"
FEED_URL = "https://feeds.bbci.co.uk/sport/rss.xml"
SOURCE_LINK = "https://www.bbc.co.uk/sport"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "BBC Sport",
    "description": "BBC Sport 官方 RSS 体育新闻。",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )
    items = parse_feed(result.data)
    if not items:
        raise RuntimeError("bbc-sport feed returned no items (empty or non-feed response)")
    return RouterData(
        **ROUTE_META,
        type="体育",
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
