from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import GOLD_CACHE_TTL, gold_item, gold_response
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zhouliufu"
SOURCE_LINK = "https://www.zlf.cn/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "周六福",
    "description": "周六福足金与工艺金人民币零售指导价",
    "link": SOURCE_LINK,
}

_ITEM_IDS = {
    "足金999‰": "gold-999",
    "足金999.9‰": "gold-9999",
    "工艺金": "craft-gold",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    soup = BeautifulSoup(str(result.data or ""), "lxml")
    quote_time = None
    for node in soup.select("div.update-time"):
        text = node.get_text(" ", strip=True)
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?", text)
        if "更新时间" in text and match:
            quote_time = match.group(0)
            break

    values: dict[str, str] = {}
    for row in soup.select("div.gold-item"):
        label = row.select_one("span.label")
        value = row.select_one("span.value")
        if label is None or value is None:
            continue
        title = label.get_text(strip=True)
        if title in _ITEM_IDS and title not in values:
            values[title] = value.get_text(strip=True)

    items = [
        gold_item(
            item_id=item_id,
            title=title,
            url=SOURCE_LINK,
            sell_price=values.get(title),
            quote_time=quote_time,
            note="零售指导价，详细金价以门店为准",
        )
        for title, item_id in _ITEM_IDS.items()
    ]
    return gold_response(route_meta=ROUTE_META, result=result, items=items)
