from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'the-verge-ai'
SOURCE_LINK = 'https://www.theverge.com/ai-artificial-intelligence'
FEED_URL = 'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'The Verge · AI',
    "description": 'The Verge coverage focused on AI.',
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"ai": "AI"},
        }
    },
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
            "Referer": SOURCE_LINK or FEED_URL,
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": parse_feed(result.data),
    }
