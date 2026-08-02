from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "nytimes"

AREA_MAP = {
    "china": "中文网",
    "global": "全球版",
}

ROUTE_META: dict = {
    "name": "nytimes",
    "title": "纽约时报",
    "params": {
        "type": {
            "name": "地区分类",
            "type": AREA_MAP,
        },
    },
    "link": "https://www.nytimes.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    area = request.query_params.get("type", "china")
    list_data = await _get_list(area, no_cache)
    return RouterData(
        **ROUTE_META,
        type=AREA_MAP.get(area, "中文网"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(area: str, no_cache: bool) -> dict:
    url = (
        "https://cn.nytimes.com/rss/"
        if area == "china"
        else "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
    )
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": parse_feed(result.data),
    }
