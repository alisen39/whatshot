from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sputniknewscn"

SOURCE_LINK = "https://sputniknews.cn/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "俄罗斯卫星通讯社",
    "description": "俄罗斯卫星通讯社中文网新闻时间线",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="快报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=urljoin(SOURCE_LINK, "services/widget/lenta/"),
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html, */*",
            "Referer": SOURCE_LINK,
        },
    )

    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    for item in soup.select(".lenta__item"):
        link = item.select_one("a")
        title_el = item.select_one(".lenta__item-text")
        date_el = item.select_one(".lenta__item-date")
        href = link.get("href") if link else ""
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not href or not title:
            continue
        url = urljoin(SOURCE_LINK, href)
        data.append(
            ListItem(
                id=_item_id(href) or url,
                title=title,
                author="俄罗斯卫星通讯社",
                timestamp=get_time(date_el.get("data-unixtime") if date_el else None),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _item_id(href: str) -> str | None:
    match = re.search(r"/(\d+)\.html", href)
    return match.group(1) if match else None
