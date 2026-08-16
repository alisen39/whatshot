from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import (
    GOLD_CACHE_TTL,
    gold_item,
    gold_quote,
    gold_response,
)
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "china-gold"
SOURCE_LINK = "https://www.chnau99999.com/page/goldPrice"
_API_URL = "https://www.chnau99999.com/page/board"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "中国黄金",
    "description": "中国黄金内地足金饰品与投资金产品人民币报价",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await post(
        url=_API_URL,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        cache_key=_API_URL,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    raw = payload.get("data") if payload.get("code") == 200 else {}
    data = raw if isinstance(raw, dict) else {}
    note = "每日参考价，实际以门店公示为准，部分货品工费另计"
    return gold_response(
        route_meta=ROUTE_META,
        result=result,
        items=[
            gold_item(
                item_id="gold-jewellery",
                title="足金饰品",
                url=SOURCE_LINK,
                sell_price=data.get("accessories"),
                note=note,
            ),
            gold_item(
                item_id="investment-gold",
                title="投资金条、储值金条、元宝金",
                url=SOURCE_LINK,
                sell_price=data.get("sel"),
                recycle_price=data.get("buy"),
                note=note,
            ),
            gold_item(
                item_id="base-gold-price",
                title="基础金价",
                url=SOURCE_LINK,
                note="官网参考基础价，不是品牌销售价或回收价",
                quotes=[
                    gold_quote(
                        quote_type="benchmark",
                        value=data.get("cur"),
                        currency="CNY",
                        unit="gram",
                    )
                ],
            ),
        ],
    )
