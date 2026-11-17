from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.backfill import LATEST_LIST_BACKFILL
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'suno-blog'
SOURCE_LINK = 'https://suno.com/blog'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Suno Blog',
    "description": 'Suno music AI product and company updates.',
    "link": SOURCE_LINK,
}
BACKFILL = LATEST_LIST_BACKFILL


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
    # The blog page renders every post as a card; no RSS exists.
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_posts(result.data)}


def _timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


_POST_PATH = re.compile(r"^/blog/(?!category/|all$)[\w-]+$")
_CATEGORY_PATH = re.compile(r"^/blog/category/")


def parse_posts(html: str) -> list[ListItem]:
    """One <article> card per post: post link, heading, category, optional excerpt, author and <time>.

    Since 2026-11 the Next.js payload no longer carries a posts array with publishedAt; the dates are
    only in the cards. The featured card has an h2 and a category link; grid cards an h3 with the
    category as a <p> inside the post link.
    """
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in BeautifulSoup(html, "lxml").select("article"):
        link = card.find("a", href=_POST_PATH)
        heading = card.find(["h2", "h3"])
        published = card.find("time", attrs={"datetime": True})
        if link is None or heading is None or published is None:
            continue
        slug = link["href"].rsplit("/", 1)[-1]
        title = heading.get_text(" ", strip=True)
        timestamp = _timestamp(published["datetime"])
        if not title or timestamp is None or slug in seen:
            continue
        seen.add(slug)
        meta = published.find_parent("p")
        category = card.find("a", href=_CATEGORY_PATH) or link.find("p")
        excerpt = next((p.get_text(" ", strip=True) for p in card.find_all("p")
                        if p is not meta and p.find_parent("a") is None), None)
        byline = meta.find("span") if meta else None
        author = byline.get_text(" ", strip=True).removeprefix("By ").strip() if byline else ""
        label = category.get_text(" ", strip=True) if category else ""
        url = f"https://suno.com/blog/{slug}"
        items.append(ListItem(id=slug, title=title, url=url, mobileUrl=url, desc=excerpt or None,
                              author=author or None, timestamp=timestamp, hotLabel=label or None))
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items
