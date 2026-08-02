from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.weread import get_weread_id

ROUTE_NAME = "weread"

type_map: dict[str, str] = {
    "rising": "飙升榜",
    "hot_search": "热搜榜",
    "newbook": "新书榜",
    "general_novel_rising": "小说榜",
    "all": "总榜",
}

ROUTE_META: dict = {
    "name": "weread",
    "title": "微信读书",
    "params": {
        "type": {
            "name": "排行榜分区",
            "type": type_map,
        },
    },
    "link": "https://weread.qq.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "rising")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "飙升榜"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://weread.qq.com/web/bookListInCategory/{type_param}?rank=1"
    result = await get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.67",
        },
        no_cache=no_cache,
    )
    items = result.data["books"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["bookInfo"]["bookId"],
                title=v["bookInfo"]["title"],
                author=v["bookInfo"].get("author"),
                desc=v["bookInfo"].get("intro"),
                cover=(v["bookInfo"].get("cover") or "").replace("s_", "t9_") or None,
                timestamp=get_time(v["bookInfo"].get("publishTime")),
                hot=v.get("readingCount"),
                url=f"https://weread.qq.com/web/bookDetail/{get_weread_id(v['bookInfo']['bookId'])}",
                mobileUrl=f"https://weread.qq.com/web/bookDetail/{get_weread_id(v['bookInfo']['bookId'])}",
            )
            for v in items
        ],
    }
