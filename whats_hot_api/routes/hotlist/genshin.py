from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "genshin"

ROUTE_META: dict = {
    "name": "genshin",
    "title": "原神",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": {
                "1": "公告",
                "2": "活动",
                "3": "资讯",
            },
        },
    },
    "link": "https://www.miyoushe.com/ys/home/28",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "1")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新动态",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList?client_type=4&gids=2&last_id=&page_size=20&type={type_param}"
    result = await get(url, no_cache=no_cache)
    items = result.data["data"]["list"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["post"]["post_id"],
                title=v["post"]["subject"],
                desc=v["post"].get("content"),
                cover=v["post"].get("cover") or (v["post"].get("images") or [None])[0],
                author=(v.get("user") or {}).get("nickname"),
                timestamp=get_time(v["post"].get("created_at")),
                hot=v["post"].get("view_status", 0),
                url=f"https://www.miyoushe.com/ys/article/{v['post']['post_id']}",
                mobileUrl=f"https://m.miyoushe.com/ys/#/article/{v['post']['post_id']}",
            )
            for v in items
        ],
    }
