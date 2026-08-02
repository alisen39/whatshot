from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hellogithub"

ROUTE_META: dict = {
    "name": "hellogithub",
    "title": "HelloGitHub",
    "description": "分享 GitHub 上有趣、入门级的开源项目",
    "params": {
        "sort": {
            "name": "排行榜分区",
            "type": {
                "featured": "精选",
                "all": "全部",
            },
        },
    },
    "link": "https://hellogithub.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    sort_param = request.query_params.get("sort", "featured")
    list_data = await _get_list(sort_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type="热门仓库",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(sort_param: str, no_cache: bool) -> dict:
    url = f"https://abroad.hellogithub.com/v1/?sort_by={sort_param}&tid=&page=1"
    result = await get(url, no_cache=no_cache)
    items = result.data["data"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["item_id"],
                title=v["title"],
                desc=v.get("summary"),
                author=v.get("author"),
                timestamp=get_time(v.get("updated_at")),
                hot=v.get("clicks_total"),
                url=f"https://hellogithub.com/repository/{v['item_id']}",
                mobileUrl=f"https://hellogithub.com/repository/{v['item_id']}",
            )
            for v in items
        ],
    }
