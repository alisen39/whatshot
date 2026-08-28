from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = '9to5mac'
SOURCE_LINK = 'https://9to5mac.com/'
FEED_URL = 'https://9to5mac.com/feed/'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": '9to5Mac',
    "description": 'Apple product news, rumors, and ecosystem coverage.',
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
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )
    data = parse_feed(result.data)
    if not data:
        raise RuntimeError("9to5Mac official feed returned no usable items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
