from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "ngabbs"

ROUTE_META: dict = {
    "name": "ngabbs",
    "title": "NGA",
    "description": "精英玩家俱乐部",
    "link": "https://ngabbs.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="论坛热帖",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://ngabbs.com/nuke.php?__lib=load_topic&__act=load_topic_reply_ladder2&opt=1&all=1"
    result = await post(
        url,
        headers={
            "Accept": "*/*",
            "Host": "ngabbs.com",
            "Referer": "https://ngabbs.com/",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-Hans-CN;q=1",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
            "X-User-Agent": "NGA_skull/7.3.1(iPhone13,2;iOS 17.2.1)",
        },
        body="__output=14",
        no_cache=no_cache,
    )
    items = result.data["result"][0]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["tid"],
                title=v["subject"],
                author=v.get("author"),
                hot=v.get("replies"),
                timestamp=get_time(v.get("postdate")),
                url=f"https://bbs.nga.cn{v['tpcurl']}",
                mobileUrl=f"https://bbs.nga.cn{v['tpcurl']}",
            )
            for v in items
        ],
    }
