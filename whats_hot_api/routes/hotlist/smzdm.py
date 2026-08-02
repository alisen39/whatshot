from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "smzdm"

_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://post.smzdm.com/rank/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
}

type_map: dict[str, str] = {
    "1": "今日热门",
    "7": "周热门",
    "30": "月热门",
}

ROUTE_META: dict = {
    "name": "smzdm",
    "title": "什么值得买",
    "description": "什么值得买是一个中立的、致力于帮助广大网友买到更有性价比网购产品的最热门推荐网站。",
    "link": "https://www.smzdm.com/top/",
    "params": {
        "type": {
            "name": "文章分类",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "1")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "今日热门"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://post.smzdm.com/rank/json_more/?unit={type_param}"
    # The upstream returns a 202 HTML anti-bot probe to generic HTTP clients.
    # Browser navigation headers select the documented JSON response.
    result = await get(url, headers=_HEADERS, no_cache=no_cache)
    items = result.data["data"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["article_id"],
                title=v["title"],
                desc=v.get("content"),
                cover=v.get("pic_url"),
                author=v.get("nickname"),
                hot=int(v.get("collection_count", 0)),
                timestamp=get_time(v.get("time_sort")),
                url=v.get("jump_link", ""),
                mobileUrl=v.get("jump_link", ""),
            )
            for v in items
        ],
    }
