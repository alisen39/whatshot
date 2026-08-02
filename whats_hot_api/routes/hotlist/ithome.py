from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ithome"

ROUTE_META: dict = {
    "name": "ithome",
    "title": "IT之家",
    "description": "爱科技，爱这里 - 前沿科技新闻网站",
    "link": "https://m.ithome.com/rankm/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _replace_link(url: str, get_id: bool = False) -> str:
    match = re.search(r"[html|live]/(\d+)\.htm", url)
    if match and match.group(1):
        num = match.group(1)
        if get_id:
            return num
        return f"https://www.ithome.com/0/{num[:3]}/{num[3:]}.htm"
    return url


async def _get_list(no_cache: bool) -> dict:
    url = "https://m.ithome.com/rankm/"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    soup = BeautifulSoup(result.data, "lxml")
    items = soup.select(".rank-box .placeholder")
    data = []
    for item in items:
        a_tag = item.select_one("a")
        href = a_tag.get("href", "") if a_tag else ""
        title_el = item.select_one(".plc-title")
        title = title_el.get_text().strip() if title_el else ""
        img_el = item.select_one("img")
        cover = img_el.get("data-original") if img_el else None
        time_el = item.select_one("span.post-time")
        time_text = time_el.get_text().strip() if time_el else ""
        review_el = item.select_one(".review-num")
        review_text = review_el.get_text() if review_el else ""
        hot_num = int(re.sub(r"\D", "", review_text)) if re.sub(r"\D", "", review_text) else 0

        data.append(
            ListItem(
                id=int(_replace_link(href, True)) if href else 100000,
                title=title,
                cover=cover,
                timestamp=get_time(time_text),
                hot=hot_num,
                url=_replace_link(href) if href else "",
                mobileUrl=_replace_link(href) if href else "",
            )
        )
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
