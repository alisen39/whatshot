from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "geekpark"

ROUTE_META: dict = {
    "name": "geekpark",
    "title": "极客公园",
    "description": "极客公园聚焦互联网领域，跟踪新鲜的科技新闻动态，关注极具创新精神的科技产品。",
    "link": "https://www.geekpark.net/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://mainssl.geekpark.net/api/v2"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("homepage_posts", [])
    data = []
    for v in items:
        post = v.get("post", {})
        authors = post.get("authors") or []
        author = authors[0].get("nickname") if authors else None
        post_id = post["id"]
        data.append(
            ListItem(
                id=post_id,
                title=post["title"],
                desc=post.get("abstract"),
                cover=post.get("cover_url"),
                author=author,
                hot=post.get("views"),
                timestamp=get_time(post.get("published_timestamp")),
                url=f"https://www.geekpark.net/news/{post_id}",
                mobileUrl=f"https://www.geekpark.net/news/{post_id}",
            )
        )
    return RouterData(
        **ROUTE_META,
        type="热门文章",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
