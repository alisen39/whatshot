from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "tieba"

ROUTE_META: dict = {
    "name": "tieba",
    "title": "百度贴吧",
    "description": "全球领先的中文社区",
    "link": "https://tieba.baidu.com/hottopic/browse/topicList",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://tieba.baidu.com/hottopic/browse/topicList"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", {}).get("bang_topic", {}).get("topic_list", [])
    data = [
        ListItem(
            id=v["topic_id"],
            title=v["topic_name"],
            desc=v.get("topic_desc"),
            cover=v.get("topic_pic"),
            hot=v.get("discuss_num"),
            timestamp=get_time(v.get("create_time")),
            url=v["topic_url"],
            mobileUrl=v["topic_url"],
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="热议榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
