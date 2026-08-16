from __future__ import annotations

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "laofengxiang-gd"
SOURCE_LINK = "http://www.lfx1848.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "老凤祥（广东）",
    "description": "老凤祥广东品牌管理中心足金与金条人民币报价",
    "link": SOURCE_LINK,
}

_ROWS = (
    ("labContent", "gold-jewellery", "足金", "gold", "retail_sell"),
    ("labContent_1", "gold-jewellery", "足金", "gold", "exchange"),
    ("labContent3", "investment-gold", "投资金条", "gold", "retail_sell"),
    ("labContent1", "jewellery-gold-bar", "饰品金条", "gold", "retail_sell"),
    ("labContent2", "platinum-950", "Pt950", "platinum", "retail_sell"),
)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        response_type="text",
    )
    soup = BeautifulSoup(str(result.data or ""), "lxml")
    date_node = soup.select_one("span#labTitle")
    quote_time = date_node.get_text(strip=True) if date_node else None
    grouped: dict[str, dict] = {}
    for span_id, item_id, title, metal, quote_type in _ROWS:
        node = soup.find("span", id=span_id)
        quote = gold_quote(
            quote_type=quote_type,
            value=node.get_text(strip=True) if node else None,
            currency="CNY",
            unit="gram",
            quote_time=quote_time,
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
            note="广东品牌管理中心参考价，口径可能仅限广东地区",
        )
        for item_id, item in grouped.items()
    ]
    return gold_response(route_meta=ROUTE_META, result=result, items=items)
