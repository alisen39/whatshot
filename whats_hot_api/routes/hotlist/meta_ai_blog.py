from __future__ import annotations

import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'meta-ai-blog'
SOURCE_LINK = 'https://ai.meta.com/blog/'
RESEARCH_LINK = 'https://research.meta.ai/'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Meta AI Blog',
    "description": 'Meta AI research and product updates.',
    "link": SOURCE_LINK,
}
# The ai.meta.com list is not in date order, so the first pages are merged and sorted.
BLOG_PAGES = 3
_DATE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")


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
    # No RSS. ai.meta.com answers 400 to desktop browser User-Agents, so the client
    # default is kept; Muse-era posts (2026-08 on) live on research.meta.ai only.
    pages = [await get(url=SOURCE_LINK, params={"page": page} if page > 1 else None, no_cache=no_cache,
                       response_type="text") for page in range(1, BLOG_PAGES + 1)]
    research = await get(url=RESEARCH_LINK, no_cache=no_cache, response_type="text")
    items = merge([*(parse_blog(p.data) for p in pages), parse_research(research.data)])
    return {"from_cache": all(p.from_cache for p in [*pages, research]), "update_time": research.update_time,
            "data": items}


def _date_ms(value: str, fmt: str) -> int | None:
    try:
        return int(datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        return None


def parse_blog(html: str) -> list[ListItem]:
    """Server-rendered <noscript> cards: date paragraph, optional category h4, title h4, link."""
    soup = BeautifulSoup(html or "", "html.parser")
    items = []
    for card in soup.select('[data-ms*="listview-card"]'):
        link = card.find("a", href=re.compile(r"^https://ai\.meta\.com/blog/[^?#]+"))
        headings = [h.get_text(" ", strip=True) for h in card.find_all("h4")]
        dates = [p.get_text(strip=True) for p in card.find_all("p") if _DATE.match(p.get_text(strip=True))]
        if not link or not headings or not dates:
            continue
        timestamp = _date_ms(dates[0], "%B %d, %Y")
        if timestamp is None:
            continue
        url = link["href"].split("?")[0]
        items.append(ListItem(id=url.rstrip("/").rsplit("/", 1)[-1], title=headings[-1], url=url, mobileUrl=url,
                              timestamp=timestamp, hotLabel=headings[0] if len(headings) > 1 else None))
    return items


def parse_research(html: str) -> list[ListItem]:
    """research.meta.ai home: <article data-blog-post-summary> cards with <time dateTime>."""
    soup = BeautifulSoup(html or "", "html.parser")
    items = []
    for card in soup.select("article[data-blog-post-summary]"):
        link = card.find("a", href=True)
        time = card.find("time")
        title = card.find(["h2", "h3", "h4"])
        if not link or not time or not title or not time.get("datetime"):
            continue
        href = link["href"]
        url = href if href.startswith("https://") else f"https://research.meta.ai{href}"
        timestamp = _date_ms(time["datetime"][:10], "%Y-%m-%d")
        if timestamp is None:
            continue
        items.append(ListItem(id=url.rstrip("/").rsplit("/", 1)[-1], title=title.get_text(" ", strip=True), url=url,
                              mobileUrl=url, timestamp=timestamp))
    return items


def merge(lists: list[list[ListItem]]) -> list[ListItem]:
    """Cross-posted pieces appear on both sites: one item per slug or title, newest first."""
    result: dict[str, ListItem] = {}
    titles: set[str] = set()
    for item in (i for items in lists for i in items):
        key = item.title.casefold()
        if item.id in result or key in titles:
            continue
        result[item.id] = item
        titles.add(key)
    return sorted(result.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
