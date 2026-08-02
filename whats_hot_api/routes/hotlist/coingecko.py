from __future__ import annotations

import math

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "coingecko"

type_map: dict[str, str] = {
    "market-cap": "全球加密货币市值榜",
    "trending": "24h 搜索趋势榜",
    "categories": "加密货币分类市值榜",
    "derivatives": "加密衍生品 24h 成交额榜",
    "exchanges": "加密货币交易所 24h 成交额榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "CoinGecko",
    "description": "CoinGecko 加密货币、分类与衍生品市场榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.coingecko.com/",
}

_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
_CATEGORIES_URL = "https://api.coingecko.com/api/v3/coins/categories"
_DERIVATIVES_URL = "https://api.coingecko.com/api/v3/derivatives"
_MAX_DERIVATIVES = 100
_EXCHANGES_URL = "https://api.coingecko.com/api/v3/exchanges"
_MAX_EXCHANGES = 100


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "market-cap")
    selected_type = type_param if type_param in type_map else "market-cap"
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
    if board_type == "trending":
        result = await get(
            url=_TRENDING_URL,
            no_cache=no_cache,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        rows = (result.data or {}).get("coins", [])
        data = [_trending_item(row.get("item") or {}) for row in rows]
    elif board_type == "categories":
        result = await get(
            url=_CATEGORIES_URL,
            params={"order": "market_cap_desc"},
            no_cache=no_cache,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        data = [_category_item(row) for row in result.data or []]
    elif board_type == "derivatives":
        result = await get(
            url=_DERIVATIVES_URL,
            no_cache=no_cache,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        ranked = sorted(
            (row for row in result.data or [] if _is_rankable_derivative(row)),
            key=lambda row: _number(row.get("volume_24h")) or 0,
            reverse=True,
        )[:_MAX_DERIVATIVES]
        data = [_derivative_item(row, rank) for rank, row in enumerate(ranked, start=1)]
    elif board_type == "exchanges":
        result = await get(
            url=_EXCHANGES_URL,
            params={"per_page": "250", "page": "1"},
            no_cache=no_cache,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        ranked = sorted(
            (row for row in result.data or [] if _is_rankable_exchange(row)),
            key=lambda row: _number(row.get("trade_volume_24h_btc")) or 0,
            reverse=True,
        )[:_MAX_EXCHANGES]
        data = [_exchange_item(row, rank) for rank, row in enumerate(ranked, start=1)]
    else:
        result = await get(
            url=_MARKETS_URL,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": "100",
                "page": "1",
                "sparkline": "false",
            },
            no_cache=no_cache,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        data = [_market_item(row) for row in result.data or []]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _market_item(row: dict) -> ListItem | None:
    coin_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    symbol = str(row.get("symbol") or "").upper().strip()
    if not coin_id or not name:
        return None
    url = f"https://www.coingecko.com/en/coins/{coin_id}"
    return ListItem(
        id=coin_id,
        title=f"{name} ({symbol})" if symbol else name,
        desc=(
            f"价格：${_display(row.get('current_price'))} · "
            f"24h 涨跌：{_display(row.get('price_change_percentage_24h'))}% · "
            f"市值：${_display(row.get('market_cap'))}"
        ),
        hot=row.get("market_cap"),
        cover=row.get("image"),
        url=url,
        mobileUrl=url,
    )


def _trending_item(row: dict) -> ListItem | None:
    coin_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    symbol = str(row.get("symbol") or "").upper().strip()
    if not coin_id or not name:
        return None
    detail = row.get("data") if isinstance(row.get("data"), dict) else {}
    change = detail.get("price_change_percentage_24h")
    usd_change = change.get("usd") if isinstance(change, dict) else None
    url = f"https://www.coingecko.com/en/coins/{coin_id}"
    return ListItem(
        id=coin_id,
        title=f"{name} ({symbol})" if symbol else name,
        desc=(
            f"市值排名：{row.get('market_cap_rank') or '暂无'} · "
            f"价格：${_display(detail.get('price'))} · "
            f"24h 涨跌：{_display(usd_change)}%"
        ),
        cover=row.get("large") or row.get("small") or row.get("thumb"),
        url=url,
        mobileUrl=url,
    )


def _category_item(row: dict) -> ListItem | None:
    category_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not category_id or not name:
        return None
    url = f"https://www.coingecko.com/en/categories/{category_id}"
    return ListItem(
        id=category_id,
        title=name,
        desc=(
            f"24h 成交额：${_display(row.get('volume_24h'))} · "
            f"24h 市值涨跌：{_display(row.get('market_cap_change_24h'))}%"
        ),
        hot=row.get("market_cap"),
        url=url,
        mobileUrl=url,
    )


def _is_rankable_derivative(row: object) -> bool:
    if not isinstance(row, dict) or row.get("expired_at"):
        return False
    market = str(row.get("market") or "").strip()
    symbol = str(row.get("symbol") or "").strip()
    contract_type = str(row.get("contract_type") or "").strip()
    volume = _number(row.get("volume_24h"))
    return bool(market and symbol and contract_type and volume is not None and volume >= 0)


def _derivative_item(row: dict, rank: int) -> ListItem | None:
    if not _is_rankable_derivative(row):
        return None
    market = str(row["market"]).strip()
    symbol = str(row["symbol"]).strip()
    contract_type = str(row["contract_type"]).strip()
    index_id = str(row.get("index_id") or "").strip()
    volume = _number(row.get("volume_24h"))
    if volume is None:
        return None
    item_id = "|".join((market, symbol, contract_type, index_id))
    details = [
        f"排名：{rank}",
        f"合约：{contract_type}",
        f"24h 成交额：${_money(volume)}",
    ]
    if index_id:
        details.append(f"指数标的：{index_id}")
    if (price := _number(row.get("price"))) is not None:
        details.append(f"标记价：${_display(price)}")
    if (change := _number(row.get("price_percentage_change_24h"))) is not None:
        details.append(f"24h 涨跌：{change:+.2f}%")
    if (funding := _number(row.get("funding_rate"))) is not None:
        details.append(f"资金费率：{funding:.6g}%")
    if (open_interest := _number(row.get("open_interest"))) is not None:
        details.append(f"未平仓量：${_money(open_interest)}")
    url = "https://www.coingecko.com/en/derivatives"
    return ListItem(
        id=item_id,
        title=f"{market} · {symbol}",
        desc=" · ".join(details),
        hot=volume,
        url=url,
        mobileUrl=url,
    )


def _is_rankable_exchange(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    exchange_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    volume = _number(row.get("trade_volume_24h_btc"))
    return bool(exchange_id and name and volume is not None and volume >= 0)


def _exchange_item(row: dict, rank: int) -> ListItem | None:
    if not _is_rankable_exchange(row):
        return None
    exchange_id = str(row["id"]).strip()
    name = str(row["name"]).strip()
    volume = _number(row.get("trade_volume_24h_btc"))
    if volume is None:
        return None
    details = [f"排名：{rank}", f"24h 成交额：{_money(volume)} BTC"]
    if (trust_score := _number(row.get("trust_score"))) is not None:
        details.append(f"信任分：{trust_score:g}")
    if (country := str(row.get("country") or "").strip()):
        details.append(f"地区：{country}")
    if (year := _number(row.get("year_established"))) is not None:
        details.append(f"成立：{year:.0f}")
    url = f"https://www.coingecko.com/en/exchanges/{exchange_id}"
    return ListItem(
        id=exchange_id,
        title=name,
        desc=" · ".join(details),
        hot=volume,
        cover=str(row.get("image") or "").strip() or None,
        url=url,
        mobileUrl=url,
    )


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value: float) -> str:
    absolute = abs(value)
    for threshold, suffix in (
        (1_000_000_000_000, "T"),
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ):
        if absolute >= threshold:
            return f"{value / threshold:.2f}{suffix}"
    return f"{value:.2f}"


def _display(value: object) -> str:
    if value is None:
        return "暂无"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)
