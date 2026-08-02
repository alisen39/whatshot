from __future__ import annotations

import time

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_current_datetime
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "history"

ROUTE_META: dict = {
    "name": "history",
    "title": "历史上的今天",
    "link": "https://baike.baidu.com/calendar",
    "params": {
        "month": "月份",
        "day": "日期",
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    dt = get_current_datetime(pad_zero=True)
    day = request.query_params.get("day", dt["day"])
    month = request.query_params.get("month", dt["month"])
    month_str = str(month).zfill(2)
    day_str = str(day).zfill(2)
    url = f"https://baike.baidu.com/cms/home/eventsOnHistory/{month_str}.json"
    result = await get(
        url=url,
        no_cache=no_cache,
        params={"_": int(time.time() * 1000)},
        cache_key=url,
    )
    month_data = result.data.get(month_str, {})
    items = month_data.get(month_str + day_str, [])
    data = []
    for index, v in enumerate(items):
        title_text = BeautifulSoup(v.get("title", ""), "html.parser").get_text(strip=True)
        desc_text = BeautifulSoup(v.get("desc", ""), "html.parser").get_text(strip=True)
        cover = v.get("pic_share") if v.get("cover") else None
        data.append(
            ListItem(
                id=index,
                title=title_text,
                cover=cover,
                desc=desc_text,
                timestamp=None,
                hot=None,
                url=v.get("link", ""),
                mobileUrl=v.get("link", ""),
            )
        )
    return RouterData(
        **ROUTE_META,
        type=f"{month}-{day}",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
