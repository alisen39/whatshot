from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from starlette.requests import Request

from whats_hot_api.models import GoldMetal, GoldQuoteType, RouterData
from whats_hot_api.routes.gold._common import (
    WEB_HEADERS,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.get_time import CHINA_TZ
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "beijing-rtj"
SOURCE_LINK = "http://beijingrtj.com/index.php"
MOBILE_LINK = "http://beijingrtj.com/phone.html"
_API_URL = "http://beijingrtj.com/admin/get_price5.php"
_CACHE_TTL = 30

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "融通金（北京）",
    "description": "融通金北京贵金属行情与饰品回购人民币/克报价",
    "link": SOURCE_LINK,
}

_ProductSpec = tuple[str, str, GoldMetal, tuple[tuple[int, GoldQuoteType], ...]]

_PRODUCTS: tuple[_ProductSpec, ...] = (
    ("market-gold", "黄金", "gold", ((1, "buyback"), (2, "retail_sell"))),
    ("market-silver", "白银", "silver", ((3, "buyback"), (4, "retail_sell"))),
    ("market-platinum", "铂金", "platinum", ((5, "buyback"), (6, "retail_sell"))),
    ("market-palladium", "钯金", "palladium", ((7, "buyback"), (8, "retail_sell"))),
    ("market-hong-kong-gold", "港金", "gold", ((9, "buyback"), (10, "retail_sell"))),
    ("jewellery-pure-gold", "千足金", "gold", ((11, "buyback"),)),
    ("jewellery-18k-gold", "18K（黄金）", "gold", ((12, "buyback"),)),
    ("jewellery-pt950", "Pt950", "platinum", ((13, "buyback"),)),
    ("jewellery-pd990", "Pd990", "palladium", ((14, "buyback"),)),
    ("jewellery-ag925", "Ag925", "silver", ((15, "buyback"),)),
)


def _source_quote_time(value: str, fetched_at: str) -> str | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", value.strip())
    if match is None:
        return None
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    local_fetched = fetched.astimezone(CHINA_TZ)
    hour, minute, second = (int(part) for part in match.groups())
    try:
        candidate = local_fetched.replace(
            hour=hour,
            minute=minute,
            second=second,
            microsecond=0,
        )
    except ValueError:
        return None
    if candidate > local_fetched + timedelta(minutes=5):
        candidate -= timedelta(days=1)
    if abs((local_fetched - candidate).total_seconds()) > 15 * 60:
        return None
    return candidate.isoformat()


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await post(
        url=_API_URL,
        headers={
            **WEB_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        no_cache=no_cache,
        ttl=_CACHE_TTL,
        response_type="text",
    )
    fields = [field.strip() for field in str(result.data or "").split(",")]
    values = fields if fields and fields[0].lower() == "price" else []
    quote_time = (
        _source_quote_time(values[16], result.update_time) if len(values) > 16 else None
    )

    items = []
    for item_id, title, metal, quote_specs in _PRODUCTS:
        quotes = [
            gold_quote(
                quote_type=quote_type,
                value=values[index] if len(values) > index else None,
                currency="CNY",
                unit="gram",
                quote_time=quote_time,
                label="回购价" if quote_type == "buyback" else None,
            )
            for index, quote_type in quote_specs
        ]
        items.append(
            gold_item(
                item_id=item_id,
                title=title,
                url=SOURCE_LINK,
                mobile_url=MOBILE_LINK,
                metal=metal,
                quote_time=quote_time,
                quotes=quotes,
                note="官网实时参考价，实际交易以门店报价为准",
            )
        )

    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=items,
        type_label="贵金属实时行情 · CNY/克",
    )
