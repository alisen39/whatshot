from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "yystv"

ROUTE_META: dict = {
    "name": "yystv",
    "title": "游研社",
    "description": "游研社是以游戏内容为主的新媒体，出品内容包括大量游戏、动漫有关的研究文章和社长聊街机、社长说、游研剧场、老四强等系列视频内容。",
    "link": "https://www.yystv.cn/docs",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.yystv.cn/home/get_home_docs_by_page"
    result = await get(
        url=url,
        no_cache=no_cache,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
            ),
        },
    )
    items = result.data.get("data", [])
    data = [
        ListItem(
            id=v["id"],
            title=v["title"],
            cover=v.get("cover"),
            author=v.get("author"),
            hot=None,
            timestamp=get_time(v.get("createtime")),
            url=f"https://www.yystv.cn/p/{v['id']}",
            mobileUrl=f"https://www.yystv.cn/p/{v['id']}",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="全部文章",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
