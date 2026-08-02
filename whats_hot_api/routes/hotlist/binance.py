from __future__ import annotations

from decimal import Decimal, InvalidOperation

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "binance"

type_map: dict[str, str] = {
    "volume": "USDT 24h 成交额榜",
    "gainers": "USDT 24h 涨幅榜",
    "losers": "USDT 24h 跌幅榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Binance",
    "description": "Binance USDT 现货交易对 24 小时行情榜",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.binance.com/en/markets/overview",
}

_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
_MIN_MOVEMENT_QUOTE_VOLUME = Decimal("1000000")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "volume")
    selected_type = type_param if type_param in type_map else "volume"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    result = await get(
        url=_TICKER_URL,
        no_cache=no_cache,
        headers={"Accept": "application/json"},
    )
    rows = _select_rows(result.data if isinstance(result.data, list) else [], board_type)
    data: list[ListItem] = []
    for row in rows[:50]:
        symbol = str(row.get("symbol") or "")
        base_asset = symbol.removesuffix("USDT")
        price = str(row.get("lastPrice") or "")
        change = str(row.get("priceChangePercent") or "")
        quote_volume = _decimal(row.get("quoteVolume"))
        item_url = f"https://www.binance.com/en/trade/{base_asset}_USDT?type=spot"
        data.append(
            ListItem(
                id=symbol,
                title=f"{base_asset}/USDT",
                desc=(
                    f"现价：{price} USDT · 24h 涨跌：{change}% · "
                    f"24h 成交额：{quote_volume:f} USDT"
                ),
                hot=int(quote_volume),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _select_rows(rows: list[dict], board_type: str) -> list[dict]:
    candidates = [
        row
        for row in rows
        if str(row.get("symbol") or "").endswith("USDT")
        and _decimal(row.get("quoteVolume")) > 0
    ]
    if board_type in {"gainers", "losers"}:
        candidates = [
            row
            for row in candidates
            if _decimal(row.get("quoteVolume")) >= _MIN_MOVEMENT_QUOTE_VOLUME
        ]
        return sorted(
            candidates,
            key=lambda row: _decimal(row.get("priceChangePercent")),
            reverse=board_type == "gainers",
        )
    return sorted(
        candidates,
        key=lambda row: _decimal(row.get("quoteVolume")),
        reverse=True,
    )


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value or "0"))
        return parsed if parsed.is_finite() else Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
