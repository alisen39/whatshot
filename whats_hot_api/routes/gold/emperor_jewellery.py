from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    WEB_HEADERS,
    gold_item,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "emperor-jewellery"
SOURCE_LINK = "https://www.emperorwatchjewellery.com/en/gold-price/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "英皇珠宝",
    "description": "英皇珠宝香港足金饰品港币/两报价",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        headers={**WEB_HEADERS, "Accept-Language": "en-US,en;q=0.9"},
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    match = re.search(
        r"Selling Price:\s*HK\$\s*([\d,]+(?:\.\d+)?)\s*/tael"
        r".{0,80}?Buying Price:\s*HK\$\s*([\d,]+(?:\.\d+)?)\s*/tael",
        str(result.data or ""),
        flags=re.DOTALL,
    )
    sell_price, recycle_price = match.groups() if match else (None, None)
    item = gold_item(
        item_id="gold-ornaments",
        title="Gold Ornaments",
        url=SOURCE_LINK,
        sell_price=sell_price,
        recycle_price=recycle_price,
        currency="HKD",
        unit="tael",
        note="品牌未提供报价时间；价格仅供参考，以香港门店公示为准",
    )
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=[item],
        type_label="中国香港 · HKD",
    )
