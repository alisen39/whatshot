from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hostloc"

TYPE_MAP = {
    "hot": "最新热门",
    "digest": "最新精华",
    "new": "最新回复",
    "newthread": "最新发表",
}

ROUTE_META: dict = {
    "name": "hostloc",
    "title": "全球主机交流",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": TYPE_MAP,
        },
    },
    "link": "https://hostloc.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_ = request.query_params.get("type", "hot")
    list_data = await _get_list(type_, no_cache)
    return RouterData(
        **ROUTE_META,
        type=TYPE_MAP.get(type_, "最新热门"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_: str, no_cache: bool) -> dict:
    url = f"https://hostloc.com/forum.php?mod=guide&view={type_}&rss=1"
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
