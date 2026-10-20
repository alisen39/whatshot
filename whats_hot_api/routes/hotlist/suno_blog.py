from __future__ import annotations

from datetime import datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.nextjs import first_list

ROUTE_NAME = 'suno-blog'
SOURCE_LINK = 'https://suno.com/blog'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Suno Blog',
    "description": 'Suno music AI product and company updates.',
    "link": SOURCE_LINK,
}


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
    # The blog page embeds every post (title, slug, publishedAt, excerpt) in its Next.js payload; no RSS exists.
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_posts(result.data)}


def _timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def parse_posts(html: str) -> list[ListItem]:
    items: list[ListItem] = []
    seen: set[str] = set()
    for post in first_list(html, "posts"):
        if not isinstance(post, dict):
            continue
        slug = (post.get("slug") or {}).get("current") if isinstance(post.get("slug"), dict) else post.get("slug")
        title = str(post.get("title") or "").strip()
        timestamp = _timestamp(post.get("publishedAt"))
        # A post without publishedAt is a draft-like page; the sitemap stamps it with "now".
        if not slug or not title or timestamp is None or slug in seen:
            continue
        seen.add(slug)
        url = f"https://suno.com/blog/{slug}"
        tags = [t for t in post.get("tags") or [] if isinstance(t, str)]
        items.append(ListItem(id=slug, title=title, url=url, mobileUrl=url, desc=post.get("excerpt") or None,
                              author=post.get("author") or None, timestamp=timestamp,
                              hotLabel=tags[0] if tags else None))
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items
