from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "arxiv-cs-cv"
SOURCE_LINK = "https://arxiv.org/list/cs.CV/recent"
FEED_URL = (
    "https://export.arxiv.org/api/query?search_query=cat%3Acs.CV&start=0&"
    "max_results=2000&sortBy=submittedDate&sortOrder=descending"
)
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "arXiv · cs.CV",
    "description": "Recent computer vision papers from arXiv.",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"cs-cv": "cs.CV"},
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
    result = await get(url=FEED_URL, no_cache=no_cache, response_type="text")
    data = parse_feed(result.data)
    if not data:
        raise RuntimeError("arXiv cs.CV response is not a non-empty Atom feed")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
