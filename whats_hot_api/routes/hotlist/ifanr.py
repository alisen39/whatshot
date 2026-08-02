from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ifanr"

ROUTE_META: dict = {
    "name": "ifanr",
    "title": "爱范儿",
    "description": "15秒了解全球新鲜事",
    "link": "https://www.ifanr.com/digest/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://sso.ifanr.com/api/v5/wp/buzz/?limit=20&offset=0"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("objects", [])
    data = [
        ListItem(
            id=v["id"],
            title=v["post_title"],
            desc=v.get("post_content"),
            timestamp=get_time(v.get("created_at")),
            hot=v.get("like_count") or v.get("comment_count"),
            url=v.get("buzz_original_url") or f"https://www.ifanr.com/{v.get('post_id', '')}",
            mobileUrl=v.get("buzz_original_url") or f"https://www.ifanr.com/digest/{v.get('post_id', '')}",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="快讯",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
