from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "nature-ml"
SOURCE_LINK = "https://www.nature.com/subjects/machine-learning"
FEED_URL = "https://www.nature.com/subjects/machine-learning.rss"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Nature · Machine learning",
    "description": "Machine-learning research updates from nature.com subject feeds.",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"ml": "Machine learning"},
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
            "Referer": SOURCE_LINK,
        },
    )
    # nature.com 间歇性把 idp cookie 检查页顶替 feed 返回;空解析必须报错而不是空榜
    items = parse_feed(result.data)
    if not items:
        raise RuntimeError("nature-ml feed returned no items (challenge page or empty feed)")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
    }
