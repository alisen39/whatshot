from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ithome-xijiayi"

ROUTE_META: dict = {
    "name": "ithome-xijiayi",
    "title": "IT之家「喜加一」",
    "description": "最新最全的「喜加一」游戏动态尽在这里！",
    "link": "https://www.ithome.com/zt/xijiayi",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新动态",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _replace_link(url: str, get_id: bool = False) -> str:
    match = re.search(r"https://www\.ithome\.com/0/(\d+)/(\d+)\.htm", url)
    if match and match.group(1) and match.group(2):
        combined = match.group(1) + match.group(2)
        if get_id:
            return combined
        return f"https://m.ithome.com/html/{combined}.htm"
    return url


async def _get_list(no_cache: bool) -> dict:
    url = "https://www.ithome.com/zt/xijiayi"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    soup = BeautifulSoup(result.data, "lxml")
    items = soup.select(".newslist li")
    data = []
    for item in items:
        a_tag = item.select_one("a")
        href = a_tag.get("href", "") if a_tag else ""
        time_el = item.select_one("span.time")
        time_text = time_el.get_text().strip() if time_el else ""
        # Extract datetime from format like '2024-01-01'
        time_match = re.search(r"'([^']+)'", time_text)
        date_time = time_match.group(1) if time_match else None

        title_el = item.select_one(".newsbody h2")
        title = title_el.get_text().strip() if title_el else ""

        desc_el = item.select_one(".newsbody p")
        desc = desc_el.get_text().strip() if desc_el else ""

        img_el = item.select_one("img")
        cover = img_el.get("data-original") if img_el else None

        comment_el = item.select_one(".comment")
        comment_text = comment_el.get_text() if comment_el else ""
        hot_digits = re.sub(r"\D", "", comment_text)
        hot = int(hot_digits) if hot_digits else 0

        data.append(
            ListItem(
                id=int(_replace_link(href, True)) if href else 100000,
                title=title,
                desc=desc or None,
                cover=cover,
                timestamp=get_time(date_time or 0),
                hot=hot,
                url=href or "",
                mobileUrl=_replace_link(href) if href else "",
            )
        )
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
