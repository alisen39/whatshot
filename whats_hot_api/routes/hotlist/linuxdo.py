from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "linuxdo"

type_map: dict[str, str] = {
    "hot": "周榜",
    "daily": "日榜",
    "latest": "最新",
}

_FEED_URLS: dict[str, str] = {
    "hot": "https://linux.do/top.rss?period=weekly",
    "daily": "https://linux.do/top.rss?period=daily",
    "latest": "https://linux.do/latest.rss",
}

ROUTE_META: dict = {
    "name": "linuxdo",
    "title": "Linux.do",
    "description": "Linux.do 技术社区话题",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://linux.do/top/weekly",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    selected_type = type_param if type_param in type_map else "hot"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **{
            **ROUTE_META,
            "link": (
                "https://linux.do/latest"
                if selected_type == "latest"
                else f"https://linux.do/top?period={'daily' if selected_type == 'daily' else 'weekly'}"
            ),
        },
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = _FEED_URLS.get(type_param, _FEED_URLS["hot"])
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": parse_feed(result.data),
    }
