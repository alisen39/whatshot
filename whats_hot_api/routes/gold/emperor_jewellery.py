from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    WEB_HEADERS,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "emperor-jewellery"
SOURCE_LINK = "https://www.emperorwatchjewellery.com/zh/gold-price/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "英皇珠宝",
    "description": "英皇珠宝香港黄金与铂金产品港币/两报价",
    "link": SOURCE_LINK,
}

_ITEM_SPECS = {
    "足金飾品": ("gold-ornaments", "足金飾品", "gold"),
    "足金金粒": ("gold-pellet", "足金金粒", "gold"),
    "足金金條": ("gold-bars", "足金金條", "gold"),
    "足鉑金首飾": ("platinum-990-ornaments", "足鉑金首飾", "platinum"),
    "黃鉑金首飾": ("gold-platinum-ornaments", "黃鉑金首飾", "platinum"),
    # Keep English aliases as a defensive fallback while always displaying Chinese.
    "Gold Ornaments": ("gold-ornaments", "足金飾品", "gold"),
    "Gold Pellet": ("gold-pellet", "足金金粒", "gold"),
    "Gold Bars": ("gold-bars", "足金金條", "gold"),
    "990 Platinum Ornaments": (
        "platinum-990-ornaments",
        "足鉑金首飾",
        "platinum",
    ),
    "Gold & Platinum Ornaments": (
        "gold-platinum-ornaments",
        "黃鉑金首飾",
        "platinum",
    ),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        headers={**WEB_HEADERS, "Accept-Language": "zh-HK,zh;q=0.9"},
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    body = str(result.data or "")
    soup = BeautifulSoup(body, "lxml")
    update_node = soup.select_one("p.last-updated")
    update_match = re.search(
        r"(?:最後更新時間|最后更新时间|Last\s+Update)\s*:\s*"
        r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})",
        update_node.get_text(" ", strip=True) if update_node else "",
        flags=re.IGNORECASE,
    )
    quote_time = update_match.group(1) if update_match else None

    items = []
    for row in soup.select(
        "section.gold-price-table div.gold-table-desktop div.body div.row"
    ):
        name_node = row.select_one("span.name")
        sell_node = row.select_one("span.sell-price")
        buy_node = row.select_one("span.buy-price")
        title = name_node.get_text(" ", strip=True) if name_node else ""
        spec = _ITEM_SPECS.get(title)
        if spec is None:
            continue
        item_id, display_title, metal = spec
        items.append(
            gold_item(
                item_id=item_id,
                title=display_title,
                url=SOURCE_LINK,
                metal=metal,
                quote_time=quote_time,
                quotes=[
                    gold_quote(
                        quote_type="retail_sell",
                        value=sell_node.get_text(strip=True) if sell_node else None,
                        currency="HKD",
                        unit="tael",
                        quote_time=quote_time,
                    ),
                    gold_quote(
                        quote_type="buyback",
                        value=buy_node.get_text(strip=True) if buy_node else None,
                        currency="HKD",
                        unit="tael",
                        quote_time=quote_time,
                    ),
                ],
                note="价格仅供参考，以香港门店实际交易价为准",
            )
        )

    if not items:
        match = re.search(
            r"Selling Price:\s*HK\$\s*([\d,]+(?:\.\d+)?)\s*/tael"
            r".{0,80}?Buying Price:\s*HK\$\s*([\d,]+(?:\.\d+)?)\s*/tael",
            body,
            flags=re.DOTALL,
        )
        sell_price, recycle_price = match.groups() if match else (None, None)
        items = [
            gold_item(
                item_id="gold-ornaments",
                title="足金飾品",
                url=SOURCE_LINK,
                sell_price=sell_price,
                recycle_price=recycle_price,
                quote_time=quote_time,
                currency="HKD",
                unit="tael",
                note="价格仅供参考，以香港门店实际交易价为准",
            )
        ]
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=items,
        type_label="中国香港 · HKD",
    )
