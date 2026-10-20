from __future__ import annotations

from datetime import datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.nextjs import first_list

ROUTE_NAME = 'runway-news'
SOURCE_LINK = 'https://runway.com/news'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Runway News',
    "description": 'Runway product, research, and company news.',
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"news": "News"},
        }
    },
}
# Customer stories share the news index but are not announcements.
_EXCLUDED_PREFIXES = ("/customers/",)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="News",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # runwayml.com/news redirects here; the page embeds every post in its Next.js payload (no RSS).
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
        href = str(post.get("href") or "")
        title = str(post.get("title") or "").strip()
        timestamp = _timestamp(post.get("date"))
        if not href.startswith("/") or href.startswith(_EXCLUDED_PREFIXES) or not title or timestamp is None:
            continue
        if href in seen:
            continue
        seen.add(href)
        url = f"https://runway.com{href}"
        description = post.get("excerpt") or post.get("seoDescription")
        items.append(ListItem(id=href.strip("/"), title=title, url=url, mobileUrl=url,
                              desc=description if isinstance(description, str) and description != "$undefined" else None,
                              cover=post.get("thumbnail") if str(post.get("thumbnail") or "").startswith("https://") else None,
                              timestamp=timestamp,
                              hotLabel=post.get("categoryLabel") if isinstance(post.get("categoryLabel"), str) else None))
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items
