from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "douban-group"

ROUTE_META: dict = {
    "name": "douban-group",
    "title": "豆瓣讨论",
    "link": "https://www.douban.com/group/explore",
}


def _get_numbers(text: str | None) -> int:
    if not text:
        return 100000000
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 100000000


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.douban.com/group/explore"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    soup = BeautifulSoup(result.data, "html.parser")
    items = soup.select(".article .channel-item")
    data = []
    for item in items:
        h3_a = item.select_one("h3 a")
        href = h3_a.get("href", "") if h3_a else ""
        item_id = _get_numbers(href)
        title = h3_a.get_text(strip=True) if h3_a else ""
        img_tag = item.select_one(".pic-wrap img")
        cover = img_tag.get("src") if img_tag else None
        desc_el = item.select_one(".block p")
        desc = desc_el.get_text(strip=True) if desc_el else None
        pubtime_el = item.select_one("span.pubtime")
        timestamp = get_time(pubtime_el.get_text(strip=True)) if pubtime_el else None
        data.append(
            ListItem(
                id=item_id,
                title=title,
                cover=cover,
                desc=desc,
                timestamp=timestamp,
                hot=0,
                url=href or f"https://www.douban.com/group/topic/{item_id}",
                mobileUrl=f"https://m.douban.com/group/topic/{item_id}/",
            )
        )
    return RouterData(
        **ROUTE_META,
        type="讨论精选",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
