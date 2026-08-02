from __future__ import annotations

import time

from starlette.requests import Request

from whats_hot_api.models import GoldItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zdf"

SOURCE_LINK = "https://www.ctfmall.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "周大福",
    "description": "最新金价实时行情，包括饰品金和投资金",
    "link": SOURCE_LINK,
}


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _price_text(sell_price: int | None, recycle_price: int | None = None) -> str:
    if recycle_price is None:
        return f"销售价：{sell_price or 0} 元/克"
    return f"销售价：{sell_price or 0} 元/克，回收价：{recycle_price} 元/克"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        kind="gold",
        type="金价实时行情",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://api2.ctfmall.com/gateway//ctfmall-common2-server/common/ctfTodayGoldPrice"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=60,
        params={"timestamp": int(time.time() * 1000)},
        cache_key=url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) "
                "Gecko/20100101 Firefox/137.0"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "appId": "ctfmall-web",
            "uid": "0",
            "idToken": "",
            "Origin": SOURCE_LINK.rstrip("/"),
            "DNT": "1",
            "Referer": SOURCE_LINK,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        },
    )

    payload = result.data or {}
    gold_price = payload.get("data") or {}
    if payload.get("code") != 200 or not isinstance(gold_price, dict):
        return {"from_cache": result.from_cache, "update_time": result.update_time, "data": []}

    price_date = gold_price.get("todayDate")
    timestamp = get_time(price_date)
    shipin_sell = _to_int(gold_price.get("todayPriceHK"))
    invest_sell = _to_int(gold_price.get("todayPriceTzjt"))
    recycle = _to_int(gold_price.get("baiJianHJPrice"))
    service_sell = _to_int(gold_price.get("todayPriceHgjShi"))
    platinum_sell = _to_int(gold_price.get("touziZuboPrice"))
    platinum_recycle = _to_int(gold_price.get("touziZuboHJPrice"))

    data = [
        GoldItem(
            id="shipin",
            title="足金（饰品、工艺品）",
            desc=_price_text(shipin_sell, recycle),
            timestamp=timestamp,
            url=SOURCE_LINK,
            sellPrice=shipin_sell,
            recyclePrice=recycle,
        ),
        GoldItem(
            id="touzi",
            title="投资黄金类",
            desc=_price_text(invest_sell, recycle),
            timestamp=timestamp,
            url=SOURCE_LINK,
            sellPrice=invest_sell,
            recyclePrice=recycle,
        ),
        GoldItem(
            id="zengzhi",
            title="黄金增值服务金价",
            desc=_price_text(service_sell),
            timestamp=timestamp,
            url=SOURCE_LINK,
            sellPrice=service_sell,
        ),
        GoldItem(
            id="bojin",
            title="铂金",
            desc=_price_text(platinum_sell, platinum_recycle),
            timestamp=timestamp,
            url=SOURCE_LINK,
            sellPrice=platinum_sell,
            recyclePrice=platinum_recycle,
        ),
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
