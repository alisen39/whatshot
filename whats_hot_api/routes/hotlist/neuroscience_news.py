from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "neuroscience-news"
SOURCE_LINK = "https://neurosciencenews.com/"
FEED_URL = "https://news.google.com/rss/search?q=site%3Aneurosciencenews.com"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Neuroscience News",
    "description": "Neuroscience and psychology research news.",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="RSS",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(url=FEED_URL, no_cache=no_cache, response_type="text")
    data = parse_feed(result.data)
    if not data:
        raise RuntimeError("Neuroscience News response is not a non-empty RSS feed")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
