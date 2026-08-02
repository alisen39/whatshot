from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "thepaper"

type_map = {
    "hot": "热榜",
    "finance": "财经资讯",
    "editor": "编辑精选",
}

_DATA_KEYS = {
    "hot": "hotNews",
    "finance": "financialInformationNews",
    "editor": "editorHandpicked",
}

ROUTE_META: dict = {
    "name": "thepaper",
    "title": "澎湃新闻",
    "description": "澎湃新闻热榜、财经资讯与编辑精选",
    "link": "https://www.thepaper.cn/",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "hot")
    selected_type = requested_type if requested_type in type_map else "hot"
    url = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", {}).get(_DATA_KEYS[selected_type], [])
    data = [
        ListItem(
            id=v["contId"],
            title=v["name"],
            cover=v.get("pic"),
            hot=_integer(v.get("praiseTimes")),
            author=(v.get("nodeInfo") or {}).get("name"),
            timestamp=get_time(v.get("pubTimeLong")),
            url=f"https://www.thepaper.cn/newsDetail_forward_{v['contId']}",
            mobileUrl=f"https://m.thepaper.cn/newsDetail_forward_{v['contId']}",
        )
        for v in items
        if v.get("contId") and v.get("name")
    ]
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _integer(value: object) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
