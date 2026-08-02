from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "jianshu"

ROUTE_META: dict = {
    "name": "jianshu",
    "title": "简书",
    "description": "一个优质的创作社区",
    "link": "https://www.jianshu.com/",
}


def _get_id(url: str) -> str:
    if not url:
        return "undefined"
    match = re.search(r"([^/]+)$", url)
    return match.group(1) if match else "undefined"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.jianshu.com/"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        headers={"Referer": "https://www.jianshu.com"},
    )
    soup = BeautifulSoup(result.data, "html.parser")
    items = soup.select("ul.note-list li")
    data = []
    for item in items:
        a_tag = item.find("a")
        href = a_tag.get("href", "") if a_tag else ""
        title_el = item.select_one("a.title")
        title = title_el.get_text(strip=True) if title_el else ""
        img_tag = item.find("img")
        cover = img_tag.get("src") if img_tag else None
        abstract_el = item.select_one("p.abstract")
        desc = abstract_el.get_text(strip=True) if abstract_el else None
        nickname_el = item.select_one("a.nickname")
        author = nickname_el.get_text(strip=True) if nickname_el else None
        data.append(
            ListItem(
                id=_get_id(href),
                title=title,
                cover=cover,
                desc=desc,
                author=author,
                hot=None,
                timestamp=None,
                url=f"https://www.jianshu.com{href}",
                mobileUrl=f"https://www.jianshu.com{href}",
            )
        )
    return RouterData(
        **ROUTE_META,
        type="热门推荐",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
