from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from whats_hot_api.models import (
    GoldItem,
    GoldMetal,
    GoldQuote,
    GoldQuoteType,
    GoldUnit,
    RouterData,
)
from whats_hot_api.utils.get_time import CHINA_TZ, get_time

GOLD_CACHE_TTL = 600
WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


_QUOTE_LABELS: dict[GoldQuoteType, str] = {
    "retail_sell": "销售价",
    "buyback": "回收价",
    "exchange": "换购价",
    "exchange_alt": "换购价（另一口径）",
    "exchange_jewellery": "换珠宝价",
    "benchmark": "基础金价",
    "spot": "现货价",
}


def price(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if match is None:
        return None
    try:
        parsed = Decimal(match.group(0))
        return parsed if parsed.is_finite() and parsed > 0 else None
    except (InvalidOperation, ValueError):
        return None


def quote_timestamp(value: object) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        text = datetime(year, month, day, tzinfo=CHINA_TZ).date().isoformat()
    return get_time(text)


def source_quote_time(value: object) -> str | None:
    timestamp = quote_timestamp(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, CHINA_TZ).isoformat()


def gold_quote(
    *,
    quote_type: GoldQuoteType,
    value: object,
    currency: str,
    unit: GoldUnit,
    quote_time: object = None,
    label: str | None = None,
) -> GoldQuote | None:
    parsed = price(value)
    if parsed is None:
        return None
    normalized_time = source_quote_time(quote_time)
    return GoldQuote(
        quoteType=quote_type,
        label=label or _QUOTE_LABELS[quote_type],
        price=parsed,
        currency=currency,
        unit=unit,
        sourceQuoteTime=normalized_time,
        sourceQuoteTimeTrusted=normalized_time is not None,
    )


def gold_item(
    *,
    item_id: str,
    title: str,
    url: str,
    mobile_url: str | None = None,
    sell_price: object = None,
    recycle_price: object = None,
    quote_time: object = None,
    note: str = "",
    metal: GoldMetal = "gold",
    quotes: list[GoldQuote | None] | None = None,
    currency: str = "CNY",
    unit: GoldUnit = "gram",
) -> GoldItem | None:
    normalized_quotes = [quote for quote in (quotes or []) if quote is not None]
    if not normalized_quotes:
        normalized_quotes = [
            quote
            for quote in (
                gold_quote(
                    quote_type="retail_sell",
                    value=sell_price,
                    currency=currency,
                    unit=unit,
                    quote_time=quote_time,
                ),
                gold_quote(
                    quote_type="buyback",
                    value=recycle_price,
                    currency=currency,
                    unit=unit,
                    quote_time=quote_time,
                ),
            )
            if quote is not None
        ]
    if not normalized_quotes:
        return None
    parts = [
        f"{quote.label}：{quote.price} {quote.currency}/{quote.unit}"
        for quote in normalized_quotes
    ]
    if note:
        parts.append(note)
    return GoldItem(
        id=item_id,
        title=title,
        url=url,
        mobileUrl=mobile_url,
        metal=metal,
        quotes=normalized_quotes,
        desc="；".join(parts),
        timestamp=quote_timestamp(quote_time),
    )


def gold_response(
    *,
    route_meta: dict[str, Any],
    result: Any,
    items: list[GoldItem | None],
    type_label: str = "人民币品牌金价",
) -> RouterData:
    data = [item for item in items if item is not None]
    return RouterData(
        **route_meta,
        kind="gold",
        type=type_label,
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
