from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'openai-cookbook'
SOURCE_LINK = 'https://cookbook.openai.com/'
FEED_URL = 'https://github.com/openai/openai-cookbook/commits/main.atom'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'OpenAI Cookbook',
    "description": 'Official OpenAI cookbook examples and guides updates.',
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"cookbook": "Cookbook"},
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Atom",
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
            "Accept": "application/atom+xml, application/xml, text/xml",
        },
    )
    data = parse_feed(result.data)
    if not data:
        raise RuntimeError("OpenAI Cookbook feed returned no usable items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
