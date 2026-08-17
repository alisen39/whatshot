from __future__ import annotations

import html
import json
import re

from starlette.requests import Request

from whats_hot_api.models import GoldMetal, GoldQuoteType, GoldUnit, RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "chow-taifook-hk"
SOURCE_LINK = "https://www.chowtaifook.com/zh-hk/eshop/realtime-gold-price.html"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "周大福（香港）",
    "description": "周大福香港港币/克与港币/两品牌原生报价",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "报价地区",
            "type": {"hong-kong": "中国香港 · HKD"},
        }
    },
}

_QuoteSpec = tuple[str, str, GoldMetal, GoldQuoteType, GoldUnit]
_QUOTES: dict[str, _QuoteSpec] = {
    "Gold_Sell": ("gold-jewellery", "999.9饰金", "gold", "retail_sell", "tael"),
    "Gold_Sell_g": ("gold-jewellery", "999.9饰金", "gold", "retail_sell", "gram"),
    "Gold_Buy": ("gold-jewellery", "999.9饰金", "gold", "buyback", "tael"),
    "Gold_Buy_g": ("gold-jewellery", "999.9饰金", "gold", "buyback", "gram"),
    "Redemption_Price": ("gold-jewellery", "999.9饰金", "gold", "exchange", "tael"),
    "Redemption_Price_g": ("gold-jewellery", "999.9饰金", "gold", "exchange", "gram"),
    "Jewellery_Redemption_Price": (
        "gold-jewellery",
        "999.9饰金",
        "gold",
        "exchange_jewellery",
        "tael",
    ),
    "Jewellery_Redemption_Price_g": (
        "gold-jewellery",
        "999.9饰金",
        "gold",
        "exchange_jewellery",
        "gram",
    ),
    "Gold_Pellet_Sell": ("gold-pellet", "金粒", "gold", "retail_sell", "tael"),
    "Gold_Pellet_Sell_g": ("gold-pellet", "金粒", "gold", "retail_sell", "gram"),
    "Gold_Pellet_Buy": ("gold-pellet", "金粒", "gold", "buyback", "tael"),
    "Gold_Pellet_Buy_g": ("gold-pellet", "金粒", "gold", "buyback", "gram"),
    "Gold_Pellet_Redemption_Price": (
        "gold-pellet",
        "金粒",
        "gold",
        "exchange",
        "tael",
    ),
    "Gold_Pellet_Redemption_Price_g": (
        "gold-pellet",
        "金粒",
        "gold",
        "exchange",
        "gram",
    ),
    "Platinum": ("platinum", "足铂金", "platinum", "buyback", "tael"),
    "Platinum_g": ("platinum", "足铂金", "platinum", "buyback", "gram"),
    "Platinum_Redemption_Price": (
        "platinum",
        "足铂金",
        "platinum",
        "exchange",
        "tael",
    ),
    "Platinum_Redemption_Price_g": (
        "platinum",
        "足铂金",
        "platinum",
        "exchange",
        "gram",
    ),
}

_OFFICIAL_QUOTE_LABELS = {
    "Redemption_Price": "饰金换金价",
    "Jewellery_Redemption_Price": "饰金换珠宝价",
    "Gold_Pellet_Redemption_Price": "金粒换货价",
    "Platinum_Redemption_Price": "足铂金换货价",
}


def _extract_payload(body: str) -> dict:
    match = re.search(
        r'class=["\'][^"\']*gold-price-data[^"\']*["\'][^>]*value=["\']([^"\']+)',
        body,
    )
    if match is None:
        return {}
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        headers={"accept-language": "zh-HK,zh;q=0.9"},
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    payload = _extract_payload(str(result.data or ""))
    quote_time = payload.get("Updated_Time")
    grouped: dict[str, dict] = {}
    for raw_key, (item_id, title, metal, quote_type, unit) in _QUOTES.items():
        quote = gold_quote(
            quote_type=quote_type,
            value=payload.get(raw_key),
            currency="HKD",
            unit=unit,
            quote_time=quote_time,
            label=_OFFICIAL_QUOTE_LABELS.get(raw_key.removesuffix("_g")),
        )
        if quote is None:
            continue
        item = grouped.setdefault(
            item_id,
            {"title": title, "metal": metal, "quotes": []},
        )
        item["quotes"].append(quote)

    items = [
        gold_item(
            item_id=item_id,
            title=item["title"],
            url=SOURCE_LINK,
            metal=item["metal"],
            quotes=item["quotes"],
            quote_time=quote_time,
            note="价格只作参考，以香港门店公示为准",
        )
        for item_id, item in grouped.items()
    ]
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=items,
        type_label="中国香港 · HKD",
    )
