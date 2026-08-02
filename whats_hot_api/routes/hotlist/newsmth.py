from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "newsmth"

ROUTE_META: dict = {
    "name": "newsmth",
    "title": "水木社区",
    "description": "水木社区是一个源于清华的高知社群。",
    "link": "https://www.newsmth.net/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://wap.newsmth.net/wap/api/hot/global"
    result = await get(url=url, no_cache=no_cache)
    topics = (result.data.get("data") or {}).get("topics", [])
    data = []
    for v in topics:
        post = v.get("article", {})
        topic_id = post.get("topicId", "")
        board_title = (v.get("board") or {}).get("title", "")
        item_url = f"https://wap.newsmth.net/article/{topic_id}?title={board_title}&from=home"
        data.append(
            ListItem(
                id=v.get("firstArticleId", ""),
                title=post.get("subject", ""),
                desc=post.get("body"),
                cover=None,
                author=(post.get("account") or {}).get("name"),
                hot=None,
                timestamp=get_time(post.get("postTime")),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return RouterData(
        **ROUTE_META,
        type="热门话题",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
