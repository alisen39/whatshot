from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.backfill import LATEST_LIST_BACKFILL
from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ghxi"

SOURCE_LINK = "https://www.ghxi.com/category/all"
# The site's WordPress feed for the same "最新" category. The list page was scraped until its
# 2026-11 redesign; the feed also carries exact publish times instead of "2小时前".
FEED_URL = "https://www.ghxi.com/category/all/feed"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "果核剥壳",
    "description": "果核剥壳软件与系统工具更新",
    "link": SOURCE_LINK,
}
BACKFILL = LATEST_LIST_BACKFILL


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="软件更新",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )
    # Ids stay the post permalink, as from the list page (the feed's guid is "?p=<id>"). A new version
    # of a tool updates the same post, so the same id comes back with a new title and date.
    data = [item.model_copy(update={"id": item.url}) for item in parse_feed(result.data)]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
