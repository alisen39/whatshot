from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "barchart"

_SITE_URL = "https://www.barchart.com/options/unusual-activity/stocks"
_API_URL = "https://www.barchart.com/proxies/core-api/v1/options/get"
_MAX_ITEMS = 50
_CSRF_PATTERN = re.compile(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)', re.I)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")
_OPTION_TYPE_MAP = {"all": "全部", "call": "看涨期权", "put": "看跌期权"}

ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "Barchart",
    "description": "Barchart 美股异常期权活动榜",
    "link": _SITE_URL,
    "params": {"type": {"name": "期权类型", "type": _OPTION_TYPE_MAP}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    option_type = request.query_params.get("type", "all").lower()
    if option_type not in _OPTION_TYPE_MAP:
        option_type = "all"
    list_data = await _get_options(option_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=_OPTION_TYPE_MAP[option_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_options(option_type: str, no_cache: bool) -> dict[str, Any]:
    cache_key = f"barchart:options:{option_type}"
    if not no_cache:
        cached = await cache.get(cache_key)
        if cached:
            return {
                "from_cache": True,
                "update_time": cached.update_time,
                "data": _cached_items(cached.data),
            }

    # The anonymous site page sets the session cookie required by the public
    # proxy API and embeds a short-lived CSRF token. ``get`` uses the shared
    # per-proxy client, keeping that cookie for the immediately following call.
    page = await get(
        _SITE_URL,
        no_cache=True,
        response_type="text",
        cache_key=f"{cache_key}:session-page",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"},
    )
    csrf_match = _CSRF_PATTERN.search(str(page.data))
    if not csrf_match:
        raise ValueError("Barchart did not provide an anonymous CSRF token")

    fetch_limit = _MAX_ITEMS * (3 if option_type != "all" else 1)
    params = {
        "fields": "baseSymbol,strikePrice,expirationDate,optionType,lastPrice,volume,openInterest,volumeOpenInterestRatio,volatility",
        "orderBy": "volumeOpenInterestRatio",
        "orderDir": "desc",
        "raw": "1",
        "limit": str(fetch_limit),
    }
    payload: Any = None
    for source_list in ("options.unusual_activity.stocks.us", "options.mostActive.us"):
        result = await get(
            _API_URL,
            params={**params, "list": source_list},
            no_cache=True,
            cache_key=f"{cache_key}:{source_list}",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0", "X-CSRF-TOKEN": csrf_match.group(1)},
        )
        candidate = result.data.get("data") if isinstance(result.data, dict) else None
        if isinstance(candidate, list) and candidate:
            payload = candidate
            break
    if not isinstance(payload, list):
        raise ValueError("Barchart returned no public option rows")

    data = _build_items(payload, option_type)
    if not data:
        raise ValueError("Barchart returned no valid option rows")
    update_time = datetime.now(timezone.utc).isoformat()
    await cache.set(
        cache_key,
        CacheData(update_time=update_time, data=[item.model_dump() for item in data]),
        config.HOTLIST_CACHE_TTL,
    )
    return {"from_cache": False, "update_time": update_time, "data": data}


def _build_items(rows: list[Any], option_type: str) -> list[ListItem]:
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else row
        symbol = str(raw.get("baseSymbol") or raw.get("symbol") or "").strip().upper()
        kind = str(raw.get("optionType") or "").strip().lower()
        strike = str(raw.get("strikePrice") or "").strip()
        expiry = str(raw.get("expirationDate") or "").strip()
        ratio = _number(raw.get("volumeOpenInterestRatio"))
        if not (_SYMBOL_PATTERN.fullmatch(symbol) and kind in {"call", "put"} and strike and expiry and ratio is not None):
            continue
        if option_type != "all" and kind != option_type:
            continue
        item_id = f"{symbol}:{kind}:{strike}:{expiry}"
        if item_id in seen:
            continue
        seen.add(item_id)
        volume = _number(raw.get("volume"))
        open_interest = _number(raw.get("openInterest"))
        last = _number(raw.get("lastPrice"))
        iv = _number(raw.get("volatility"))
        detail = [f"{kind.title()} · 行权价 ${strike} · 到期 {expiry}", f"量/OI：{ratio:g}"]
        if volume is not None:
            detail.append(f"成交量：{volume:,.0f}")
        if open_interest is not None:
            detail.append(f"未平仓：{open_interest:,.0f}")
        if last is not None:
            detail.append(f"最新价：${last:g}")
        if iv is not None:
            detail.append(f"隐波：{iv:g}%")
        items.append(ListItem(
            id=item_id,
            title=f"{symbol} {kind.title()} ${strike}",
            desc=" · ".join(detail),
            hot=ratio,
            url=f"https://www.barchart.com/stocks/quotes/{symbol}/options",
            mobileUrl=f"https://www.barchart.com/stocks/quotes/{symbol}/options",
        ))
        if len(items) >= _MAX_ITEMS:
            break
    return items


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _cached_items(value: Any) -> list[ListItem]:
    return [ListItem.model_validate(item) for item in value or [] if isinstance(item, dict)]
