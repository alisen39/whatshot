from __future__ import annotations

import hashlib
import time
from decimal import Decimal, InvalidOperation

from starlette.requests import Request

from whats_hot_api.models import GoldItem, RouterData
from whats_hot_api.routes.gold._common import gold_item, gold_quote
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zdf"

SOURCE_LINK = "https://www.ctfmall.com/"
_TYPE_MAP = {"mainland": "中国内地 · CNY"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "周大福",
    "description": "最新金价实时行情，包括饰品金和投资金",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "报价地区", "type": _TYPE_MAP}},
}


def _to_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value).replace(",", ""))
        return parsed if parsed.is_finite() and parsed > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


_KNOWN_ITEM_IDS = {
    "足金": "shipin",
    "工艺金章金条类": "gongyi-jintiao",
    "投资黄金类": "touzi-huangjin",
    "黄金增值服务金价": "zengzhi",
    "黄金回收服务金价": "huishou",
}


def _item_id(display_name: str, category_group: int, sort_order: int) -> str:
    known = _KNOWN_ITEM_IDS.get(display_name)
    if known:
        return known
    identity = f"{category_group}|{sort_order}|{display_name}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"category-{category_group}-{sort_order}-{digest}"


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
    url = "https://api2.ctfmall.com/gateway//ctfmall-common2-server/common/ctfTodayGoldPriceNew"
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
        return {
            "from_cache": result.from_cache,
            "update_time": result.update_time,
            "data": [],
        }

    groups = gold_price.get("goldPriceDailyListVO")
    if not isinstance(groups, list):
        return {
            "from_cache": result.from_cache,
            "update_time": result.update_time,
            "data": [],
        }

    sortable_items: list[tuple[int, int, int, GoldItem]] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        items = group.get("goldPriceInfoListVO")
        if not isinstance(items, list):
            continue
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("isEnabled") is False or item.get("isShowInFrontend") is False:
                continue
            display_name = str(item.get("displayName") or "").strip()
            price = _to_decimal(item.get("goldPrice"))
            if not display_name or price is None:
                continue
            second_name = str(item.get("secondDisplayName") or "").strip()
            category_group = int(item.get("categoryGroup") or group_index + 1)
            sort_order = int(item.get("sortOrder") or item_index + 1)
            category_name = str(
                item.get("categoryName") or group.get("categoryName") or ""
            )
            is_recycle = (
                category_group == 3 or "回收" in category_name or "回收" in display_name
            )
            is_exchange = category_group == 2 or "增值" in category_name
            quote_type = (
                "buyback"
                if is_recycle
                else "exchange"
                if is_exchange
                else "retail_sell"
            )
            normalized_item = gold_item(
                item_id=_item_id(display_name, category_group, sort_order),
                title=f"{display_name}{second_name}",
                url=SOURCE_LINK,
                quote_time=item.get("todayDate"),
                quotes=[
                    gold_quote(
                        quote_type=quote_type,
                        value=price,
                        currency="CNY",
                        unit="gram",
                        quote_time=item.get("todayDate"),
                    )
                ],
            )
            if normalized_item is None:
                continue
            sortable_items.append(
                (
                    category_group,
                    sort_order,
                    item_index,
                    normalized_item,
                )
            )
    data = [entry[3] for entry in sorted(sortable_items, key=lambda entry: entry[:3])]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
