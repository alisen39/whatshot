from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.nextjs import flight_text, json_values

ROUTE_NAME = 'ant-bailing-blog'
SOURCE_LINK = 'https://developer.ant-ling.com/zh-CN/blogs'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Ant Bailing Developer Blog',
    "description": 'Ant Group Bailing model and developer updates.',
    "link": SOURCE_LINK,
}
_CST = timezone(timedelta(hours=8))


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Blog",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # ling-ai.antgroup.com no longer resolves; the official blog (linked from ant-ling.com) embeds
    # every post in its Next.js payload. Its canonical host docs.ant-ling.com does not resolve either.
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_posts(result.data)}


def parse_posts(html: str) -> list[ListItem]:
    items: dict[str, ListItem] = {}
    for post in json_values(flight_text(html), "post"):
        if not isinstance(post, dict):
            continue
        slug, title, date = post.get("slug"), str(post.get("title") or "").strip(), post.get("date")
        if not isinstance(slug, str) or not slug or not title or slug in items:
            continue
        try:
            # Date only, published in China time.
            timestamp = int(datetime.strptime(str(date), "%Y-%m-%d").replace(tzinfo=_CST).timestamp() * 1000)
        except ValueError:
            continue
        tags = [t for t in post.get("tags") or [] if isinstance(t, str)]
        summary = post.get("summary")
        url = f"https://developer.ant-ling.com/zh-CN/blogs/{slug}"
        items[slug] = ListItem(id=slug, title=title, url=url, mobileUrl=url, timestamp=timestamp,
                               desc=summary if isinstance(summary, str) and summary != "$undefined" else None,
                               hotLabel=tags[0] if tags else None)
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
