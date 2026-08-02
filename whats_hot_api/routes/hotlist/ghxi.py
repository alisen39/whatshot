from __future__ import annotations

import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import CHINA_TZ
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ghxi"

SOURCE_LINK = "https://www.ghxi.com/category/all"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "果核剥壳",
    "description": "果核剥壳软件与系统工具更新",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="软件更新",
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
    for element in soup.select(".sec-panel .sec-panel-body .post-loop li"):
        anchor = element.select_one(".item-content .item-title a")
        if anchor is None:
            continue
        title = anchor.get_text(" ", strip=True)
        item_url = str(anchor.get("href") or "").strip()
        if not title or not item_url:
            continue
        description = element.select_one(".item-content .item-excerpt")
        date_element = element.select_one(".item-content .date")
        data.append(
            ListItem(
                id=item_url,
                title=title,
                desc=(description.get_text(" ", strip=True) if description else None),
                timestamp=_relative_time_ms(
                    date_element.get_text(" ", strip=True) if date_element else ""
                ),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _relative_time_ms(value: str) -> int | None:
    match = re.search(r"(\d+)\s*(秒|分钟|小时|天|周|月|年)前?", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {
        "秒": 1,
        "分钟": 60,
        "小时": 60 * 60,
        "天": 24 * 60 * 60,
        "周": 7 * 24 * 60 * 60,
        "月": 30 * 24 * 60 * 60,
        "年": 365 * 24 * 60 * 60,
    }[unit]
    dt = datetime.now(CHINA_TZ) - timedelta(seconds=amount * seconds)
    return int(dt.timestamp() * 1000)
