from __future__ import annotations

import html
import json
import re

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "chowsangsang"
SOURCE_LINK = "https://cn.chowsangsang.com/gold-info"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "周生生",
    "description": "周生生中国内地足金饰品与生生金宝人民币报价",
    "link": SOURCE_LINK,
}


def _extract_prices(body: str) -> dict[str, dict]:
    unescaped = html.unescape(body)
    for match in re.finditer(r'\[\{"region"', unescaped):
        segment = unescaped[match.start() :]
        depth = 0
        in_string = False
        escaped = False
        for index, char in enumerate(segment):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    try:
                        rows = json.loads(segment[: index + 1])
                    except json.JSONDecodeError:
                        break
                    return {
                        str(row.get("type")): row
                        for row in rows
                        if isinstance(row, dict)
                        and row.get("region") == "CHN"
                        and row.get("currencyCode") == "RMB"
                        and row.get("weightUnit") == "GM"
                    }
    return {}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    rows = _extract_prices(str(result.data or ""))
    jewellery_sell = rows.get("G_JW_SELL", {})
    jewellery_buyback = rows.get("G_JW_CNTPTBUY", {})
    jewellery_exchange = rows.get("G_JW_GPEXCH", {})
    jewellery_exchange_alt = rows.get("G_JW_JWEXCH", {})
    ingot_sell = rows.get("G_INGOT_SELL", {})
    ingot_buyback = rows.get("G_INGOT_CNTPTBUY", {})
    buyback_note = "回收价由品牌选定的第三方回收方提供，仅供指定门店参考"
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=[
            gold_item(
                item_id="gold-jewellery",
                title="足金饰品",
                url=SOURCE_LINK,
                quote_time=jewellery_sell.get("lastUpdateDate"),
                note=buyback_note,
                quotes=[
                    gold_quote(
                        quote_type="retail_sell",
                        value=jewellery_sell.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=jewellery_sell.get("lastUpdateDate"),
                    ),
                    gold_quote(
                        quote_type="buyback",
                        value=jewellery_buyback.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=jewellery_buyback.get("lastUpdateDate"),
                    ),
                    gold_quote(
                        quote_type="exchange",
                        value=jewellery_exchange.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=jewellery_exchange.get("lastUpdateDate"),
                    ),
                    gold_quote(
                        quote_type="exchange_jewellery",
                        value=jewellery_exchange_alt.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=jewellery_exchange_alt.get("lastUpdateDate"),
                    ),
                ],
            ),
            gold_item(
                item_id="investment-gold",
                title="生生金宝",
                url=SOURCE_LINK,
                quote_time=ingot_sell.get("lastUpdateDate"),
                note=buyback_note,
                quotes=[
                    gold_quote(
                        quote_type="retail_sell",
                        value=ingot_sell.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=ingot_sell.get("lastUpdateDate"),
                    ),
                    gold_quote(
                        quote_type="buyback",
                        value=ingot_buyback.get("price"),
                        currency="CNY",
                        unit="gram",
                        quote_time=ingot_buyback.get("lastUpdateDate"),
                    ),
                ],
            ),
        ],
    )
