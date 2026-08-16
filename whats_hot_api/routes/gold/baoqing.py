from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    WEB_HEADERS,
    gold_item,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "baoqing"
SOURCE_LINK = "https://www.baoqing.com.cn/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "宝庆银楼",
    "description": "宝庆银楼足金饰品与黄金摆件人民币参考价",
    "link": SOURCE_LINK,
}

_ITEM_IDS = {
    "足金（饰品、工艺品类）": "gold-jewellery",
    "5G黄金摆件": "gold-5g-ornament",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        headers=WEB_HEADERS,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    soup = BeautifulSoup(str(result.data or ""), "lxml")
    values: dict[str, str] = {}
    for row in soup.select("div.jinList_li_Ri_text1"):
        name_node = row.select_one("div.jinList_li_Ri_t_le")
        price_node = row.select_one("div.jinList_li_Ri_t_ri span")
        if name_node is None or price_node is None:
            continue
        title = re.sub(r"\s+", "", name_node.get_text("", strip=True))
        if title in _ITEM_IDS:
            values[title] = price_node.get_text(strip=True)

    items = [
        gold_item(
            item_id=item_id,
            title=title,
            url=SOURCE_LINK,
            sell_price=values.get(title),
            note="今日金价以各门店公示为准，部分货品工费另计",
        )
        for title, item_id in _ITEM_IDS.items()
    ]
    return gold_response(route_meta=ROUTE_META, result=result, items=items)
