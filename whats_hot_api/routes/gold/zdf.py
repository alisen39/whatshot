from __future__ import annotations

import hashlib
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


def _price_text(sell_price: int | None, recycle_price: int | None = None) -> str:
    if sell_price is None and recycle_price is not None:
        return f"回收价：{recycle_price} 元/克"
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
        return {"from_cache": result.from_cache, "update_time": result.update_time, "data": []}

    groups = gold_price.get("goldPriceDailyListVO")
    if not isinstance(groups, list):
        return {"from_cache": result.from_cache, "update_time": result.update_time, "data": []}

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
            price = _to_int(item.get("goldPrice"))
            if not display_name or price is None:
                continue
            second_name = str(item.get("secondDisplayName") or "").strip()
            category_group = int(item.get("categoryGroup") or group_index + 1)
            sort_order = int(item.get("sortOrder") or item_index + 1)
            category_name = str(
                item.get("categoryName") or group.get("categoryName") or ""
            )
            is_recycle = category_group == 3 or "回收" in category_name or "回收" in display_name
            sell_price = None if is_recycle else price
            recycle_price = price if is_recycle else None
            sortable_items.append(
                (
                    category_group,
                    sort_order,
                    item_index,
                    GoldItem(
                        id=_item_id(display_name, category_group, sort_order),
                        title=f"{display_name}{second_name}",
                        desc=_price_text(sell_price, recycle_price),
                        timestamp=get_time(item.get("todayDate")),
                        url=SOURCE_LINK,
                        sellPrice=sell_price,
                        recyclePrice=recycle_price,
                    ),
                )
            )
    data = [entry[3] for entry in sorted(sortable_items, key=lambda entry: entry[:3])]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
