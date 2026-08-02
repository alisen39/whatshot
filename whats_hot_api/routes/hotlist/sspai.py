from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sspai"

ROUTE_META: dict = {
    "name": "sspai",
    "title": "少数派",
    "params": {
        "type": {
            "name": "分类",
            "type": ["热门文章", "应用推荐", "生活方式", "效率技巧", "少数派播客"],
        },
    },
    "link": "https://sspai.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "热门文章")
    url = f"https://sspai.com/api/v1/article/tag/page/get?limit=40&tag={type_param}"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", [])
    data = [
        ListItem(
            id=v["id"],
            title=v["title"],
            desc=v.get("summary"),
            cover=v.get("banner"),
            author=v.get("author", {}).get("nickname"),
            timestamp=get_time(v.get("released_time")),
            hot=v.get("like_count"),
            url=f"https://sspai.com/post/{v['id']}",
            mobileUrl=f"https://sspai.com/post/{v['id']}",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
