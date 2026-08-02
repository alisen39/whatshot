from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "crowdsupply"

SOURCE_LINK = "https://www.crowdsupply.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Crowd Supply",
    "description": "Open hardware launches and crowdfunding updates",
    "link": SOURCE_LINK,
}

_FUNDED_RE = re.compile(r"([\d,]+)\s*%\s*Funded", re.IGNORECASE)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Projects",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    seen: set[str] = set()
    for tile in soup.select("a.project-tile"):
        href = tile.get("href") or ""
        title = (tile.get("aria-label") or "").strip()
        if not href or not title or href in seen:
            continue
        seen.add(href)
        url = urljoin(SOURCE_LINK, href)
        desc_el = tile.select_one(".project-tile-overview p")
        img_el = tile.select_one("img")
        cover = (
            urljoin(SOURCE_LINK, img_el.get("src"))
            if img_el and img_el.get("src")
            else None
        )
        data.append(
            ListItem(
                id=href.strip("/"),
                title=title,
                cover=cover,
                desc=desc_el.get_text(" ", strip=True) if desc_el else None,
                hot=_funded_percent(tile.get_text(" ", strip=True)),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _funded_percent(text: str) -> int | None:
    match = _FUNDED_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))
