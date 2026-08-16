from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import GoldMetal, GoldQuoteType, GoldUnit, RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "lukfook"
SOURCE_LINK = "https://www.lukfook.com/sc/page/goldprice"
_HK_SOURCE_LINK = "https://www.lukfook.com/tc/page/goldprice"
_API_URL = "https://www.lukfook.com/api/goldprice/page"

_TYPE_MAP = {
    "mainland": "中国内地 · CNY",
    "hong-kong": "中国香港 · HKD",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "六福珠宝",
    "description": "六福珠宝中国内地与香港品牌原生报价",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "报价地区", "type": _TYPE_MAP}},
}

_QuoteSpec = tuple[str, str, GoldMetal, GoldQuoteType, GoldUnit]

_MAINLAND_QUOTES: dict[str, _QuoteSpec] = {
    "GoldS": ("gold-jewellery", "足金999、足金", "gold", "retail_sell", "gram"),
    "GoldT": ("gold-jewellery", "足金999、足金", "gold", "exchange", "gram"),
    "PlatinumS": ("platinum", "足铂999、足铂", "platinum", "retail_sell", "gram"),
    "PlatinumT": ("platinum", "足铂999、足铂", "platinum", "exchange", "gram"),
    "pts": ("platinum-950", "Pt950", "platinum", "retail_sell", "gram"),
    "ptc": ("platinum-950", "Pt950", "platinum", "exchange", "gram"),
    "InvestmentS": (
        "investment-gold",
        "黄金添富金、金章金条",
        "gold",
        "retail_sell",
        "gram",
    ),
    "InvestmentB": (
        "investment-gold",
        "黄金添富金、金章金条",
        "gold",
        "buyback",
        "gram",
    ),
    "InvestmentPlatinumS": (
        "investment-platinum",
        "铂金添富金、金章金条",
        "platinum",
        "retail_sell",
        "gram",
    ),
}

_HONG_KONG_QUOTES: dict[str, _QuoteSpec] = {
    "GoldS": ("gold-jewellery", "999.9饰金", "gold", "retail_sell", "gram"),
    "GoldB": ("gold-jewellery", "999.9饰金", "gold", "buyback", "gram"),
    "GoldT": ("gold-jewellery", "999.9饰金", "gold", "exchange", "gram"),
    "GoldT*": ("gold-jewellery", "999.9饰金", "gold", "exchange_alt", "gram"),
    "GoldTS": ("gold-jewellery", "999.9饰金", "gold", "retail_sell", "tael"),
    "GoldTB": ("gold-jewellery", "999.9饰金", "gold", "buyback", "tael"),
    "GoldTT": ("gold-jewellery", "999.9饰金", "gold", "exchange", "tael"),
    "GoldTT*": ("gold-jewellery", "999.9饰金", "gold", "exchange_alt", "tael"),
    "InvestmentS": ("investment-gold", "投资金", "gold", "retail_sell", "gram"),
    "InvestmentB": ("investment-gold", "投资金", "gold", "buyback", "gram"),
    "InvestmentT": ("investment-gold", "投资金", "gold", "exchange", "gram"),
    "InvestmentT*": ("investment-gold", "投资金", "gold", "exchange_alt", "gram"),
    "InvestmentTS": ("investment-gold", "投资金", "gold", "retail_sell", "tael"),
    "InvestmentTB": ("investment-gold", "投资金", "gold", "buyback", "tael"),
    "InvestmentTT": ("investment-gold", "投资金", "gold", "exchange", "tael"),
    "InvestmentTT*": ("investment-gold", "投资金", "gold", "exchange_alt", "tael"),
    "PlatinumS": ("platinum", "铂金", "platinum", "retail_sell", "gram"),
    "PlatinumB": ("platinum", "铂金", "platinum", "buyback", "gram"),
    "PlatinumT": ("platinum", "铂金", "platinum", "exchange", "gram"),
    "PlatinumTS": ("platinum", "铂金", "platinum", "retail_sell", "tael"),
    "PlatinumTB": ("platinum", "铂金", "platinum", "buyback", "tael"),
    "PlatinumTT": ("platinum", "铂金", "platinum", "exchange", "tael"),
    "GoldPieceS": ("gold-piece", "金片、金粒", "gold", "retail_sell", "gram"),
    "GoldPieceB": ("gold-piece", "金片、金粒", "gold", "buyback", "gram"),
    "GoldPieceT": ("gold-piece", "金片、金粒", "gold", "exchange", "gram"),
    "GoldPieceTS": ("gold-piece", "金片、金粒", "gold", "retail_sell", "tael"),
    "GoldPieceTB": ("gold-piece", "金片、金粒", "gold", "buyback", "tael"),
    "GoldPieceTT": ("gold-piece", "金片、金粒", "gold", "exchange", "tael"),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    region = request.query_params.get("type", "mainland")
    if region not in _TYPE_MAP:
        region = "mainland"
    is_hong_kong = region == "hong-kong"
    lang = "tc" if is_hong_kong else "sc"
    source_link = _HK_SOURCE_LINK if is_hong_kong else SOURCE_LINK
    result = await get(
        url=_API_URL,
        headers={"lang": lang},
        no_cache=no_cache,
        ttl=300 if is_hong_kong else GOLD_CACHE_TTL,
        cache_key=f"{_API_URL}?lang={lang}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    raw = payload.get("data") if payload.get("status") == 1 else {}
    data = raw if isinstance(raw, dict) else {}
    groups = data.get("group") if isinstance(data.get("group"), list) else []
    merged: dict[str, object] = {}
    for group in groups:
        if isinstance(group, dict):
            merged.update(group)

    has_hk_marker = "rmb_buyprice" in data or any(
        key in merged for key in ("GoldTS", "InvestmentTS", "PlatinumTS")
    )
    has_mainland_marker = any(key in merged for key in ("pts", "ptc"))
    if is_hong_kong and data and not has_hk_marker:
        raise ValueError("六福金价接口返回的不是中国香港港币报价")
    if not is_hong_kong and data and (has_hk_marker or not has_mainland_marker):
        raise ValueError("六福金价接口返回的不是中国内地人民币报价")

    currency = "HKD" if is_hong_kong else "CNY"
    specs = _HONG_KONG_QUOTES if is_hong_kong else _MAINLAND_QUOTES
    quote_time = data.get("record_date")
    grouped: dict[str, dict] = {}
    for raw_key, (item_id, title, metal, quote_type, unit) in specs.items():
        quote = gold_quote(
            quote_type=quote_type,
            value=merged.get(raw_key),
            currency=currency,
            unit=unit,
            quote_time=quote_time,
        )
        if quote is None:
            continue
        item = grouped.setdefault(
            item_id,
            {"title": title, "metal": metal, "quotes": []},
        )
        item["quotes"].append(quote)

    note = "价格只作参考，部分货品工费另计"
    items = [
        gold_item(
            item_id=item_id,
            title=item["title"],
            url=source_link,
            metal=item["metal"],
            quotes=item["quotes"],
            quote_time=quote_time,
            note=note,
        )
        for item_id, item in grouped.items()
    ]
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=items,
        type_label=_TYPE_MAP[region],
    )
