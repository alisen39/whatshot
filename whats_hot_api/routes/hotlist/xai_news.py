from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'xai-news'
SOURCE_LINK = 'https://x.ai/news'
SITEMAP_URL = 'https://x.ai/sitemap.xml'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'xAI News',
    "description": 'Official xAI product and company news.',
    "link": SOURCE_LINK,
}
# x.ai's WAF answers 403 to every HTTP/2 client and to non-browser User-Agents
# (verified 2026-10-19), so both requests use HTTP/1.1 with a browser UA.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/141.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_DATE = re.compile(r"^[A-Z][a-z]{2,8} \d{1,2}, \d{4}$")


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
    # Titles come from the news page, publish dates from the sitemap (lastmod = publish date).
    page = await get(url=SOURCE_LINK, headers=_HEADERS, no_cache=no_cache, response_type="text", http2=False)
    sitemap = await get(url=SITEMAP_URL, headers=_HEADERS, no_cache=no_cache, response_type="text", http2=False)
    return {"from_cache": page.from_cache and sitemap.from_cache, "update_time": page.update_time,
            "data": parse_news(page.data, parse_dates(sitemap.data))}


def parse_dates(xml: str) -> dict[str, int]:
    dates: dict[str, int] = {}
    root = ET.fromstring(xml)
    for node in root.findall(f"{_SITEMAP_NS}url"):
        loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
        lastmod = (node.findtext(f"{_SITEMAP_NS}lastmod") or "").strip()
        if not loc.startswith("https://x.ai/news/") or not lastmod:
            continue
        try:
            dates[loc.removeprefix("https://x.ai")] = int(datetime.fromisoformat(lastmod.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
    return dates


def parse_news(html: str, dates: dict[str, int]) -> list[ListItem]:
    soup = BeautifulSoup(html or "", "html.parser")
    items: dict[str, ListItem] = {}
    for link in soup.select('a[href^="/news/"]'):
        href = link["href"].split("?")[0].rstrip("/")
        if href in items or href.count("/") != 2:
            continue
        heading = link.find(["h1", "h2", "h3", "h4"]) or (link.parent.find(["h1", "h2", "h3"]) if link.parent else None)
        image = link.find("img")
        title = heading.get_text(" ", strip=True) if heading else (image.get("alt", "").strip() if image else "")
        if not title:
            continue
        texts = [p.get_text(" ", strip=True) for p in link.find_all("p")]
        description = next((t for t in texts if t and not _DATE.match(t)), None)
        url = f"https://x.ai{href}"
        items[href] = ListItem(id=href.rsplit("/", 1)[-1], title=title, url=url, mobileUrl=url,
                               desc=description, timestamp=dates.get(href))
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
