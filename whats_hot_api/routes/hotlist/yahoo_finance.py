from __future__ import annotations

import hashlib
import math
import re
from typing import Any
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "yahoo-finance"

type_map: dict[str, str] = {
    "news": "财经新闻",
    "trending": "热门股票",
    "most-active": "成交量热门",
    "day-gainers": "当日涨幅榜",
    "day-losers": "当日跌幅榜",
    "52-week-gainers": "52 周涨幅榜",
    "52-week-losers": "52 周跌幅榜",
}

ROUTE_META: dict[str, Any] = {"name": ROUTE_NAME, "title": "Yahoo Finance", "description": "Yahoo Finance 财经新闻、热门股票与美股市场榜单", "link": "https://finance.yahoo.com/markets/stocks/", "params": {"type": {"name": "榜单类型", "type": type_map}}}

_MAX_ITEMS = 25
_SYMBOL_RE = re.compile(r"^[A-Z0-9^.=-]+$")
_MARKET_TYPES: dict[str, tuple[str, str, str]] = {
    "trending": (
        "https://finance.yahoo.com/markets/stocks/trending/",
        "Trending Stocks Today",
        "tab-trending",
    ),
    "most-active": (
        "https://finance.yahoo.com/markets/stocks/",
        "Most Active Stocks Today",
        "tab-most-active",
    ),
    "day-gainers": (
        "https://finance.yahoo.com/markets/stocks/gainers/",
        "Top Stock Gainers Today",
        "tab-gainers",
    ),
    "day-losers": (
        "https://finance.yahoo.com/markets/stocks/losers/",
        "Top Stock Losers Today",
        "tab-losers",
    ),
    "52-week-gainers": (
        "https://finance.yahoo.com/markets/stocks/52-week-gainers/",
        "52 Week Stock Gainers",
        "tab-52-week-gainers",
    ),
    "52-week-losers": (
        "https://finance.yahoo.com/markets/stocks/52-week-losers/",
        "52 Week Stock Losers",
        "tab-52-week-losers",
    ),
}
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://finance.yahoo.com/markets/stocks/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
    ),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "news")
    selected = requested if requested in type_map else "news"
    if selected == "news":
        list_data = await _get_news(no_cache)
    else:
        list_data = await _get_market_table(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _normalize_news(list_data: dict[str, Any]) -> dict[str, Any]:
    data: list[ListItem] = []
    seen_urls: set[str] = set()
    for item in list_data.get("data") or []:
        if not isinstance(item, ListItem):
            return {**list_data, "data": []}
        parsed = urlsplit(item.url)
        canonical_url = (
            f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"
            f"{parsed.path.rstrip('/') or '/'}"
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or canonical_url in seen_urls
        ):
            continue
        seen_urls.add(canonical_url)
        item_id = "yf-" + hashlib.sha256(canonical_url.encode()).hexdigest()[:24]
        data.append(item.model_copy(update={"id": item_id}))
    return {**list_data, "data": data}


async def _get_news(no_cache: bool) -> dict[str, Any]:
    result = await get(url="https://finance.yahoo.com/news/rssindex", no_cache=no_cache, response_type="text", headers={**_HEADERS, "Accept": "application/rss+xml,application/xml,text/xml"})
    return _normalize_news({"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)})


async def _get_market_table(board_type: str, no_cache: bool) -> dict[str, Any]:
    url, heading, active_tab_id = _MARKET_TYPES[board_type]
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        cache_key=f"yahoo-finance:stocks:{board_type}:top-{_MAX_ITEMS}",
        headers={
            **_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_market_table(result.data, board_type, heading, active_tab_id),
    }


def _parse_trending(html_text: object) -> list[ListItem]:
    _, heading, active_tab_id = _MARKET_TYPES["trending"]
    return _parse_market_table(html_text, "trending", heading, active_tab_id)


def _parse_market_table(
    html_text: object,
    board_type: str,
    heading: str,
    active_tab_id: str,
) -> list[ListItem]:
    if not isinstance(html_text, str) or not html_text.strip():
        return []
    soup = BeautifulSoup(html_text, "lxml")
    active_tab = soup.select_one(f"#{active_tab_id}[aria-selected='true']")
    headings = {_text(node.get_text(" ", strip=True)) for node in soup.select("h1")}
    table = soup.select_one("[data-testid='markets-table-wrapper'] table")
    rows = table.select("tbody tr[data-testid='data-table-v2-row']") if table else []
    if (
        active_tab is None
        or heading not in headings
        or len(rows) != _MAX_ITEMS
    ):
        return []

    data: list[ListItem] = []
    seen_symbols: set[str] = set()
    for row in rows:
        symbol_node = row.select_one("td[data-testid-cell='ticker'] a[href]")
        name_node = row.select_one("td[data-testid-cell='companyshortname.raw']")
        price_node = row.select_one(
            "td[data-testid-cell='intradayprice'] span[data-testid='change']"
        )
        change_node = row.select_one(
            "td[data-testid-cell='intradayprice'] "
            "fin-streamer[data-field='regularMarketChangePercent'][data-value]"
        )
        symbol = _text(symbol_node.get_text(" ", strip=True) if symbol_node else "").upper()
        name = _text(name_node.get_text(" ", strip=True) if name_node else "")
        price_text = (
            price_node.get_text(" ", strip=True).replace(",", "")
            if price_node
            else None
        )
        price = _number(price_text)
        change = _number(change_node.get("data-value") if change_node else None)
        volume = _parse_compact_cell(row, "dayvolume")
        average_volume = _parse_compact_cell(row, "avgdailyvol3m")
        market_cap = _parse_compact_cell(row, "intradaymarketcap")
        week_change = _parse_percent_cell(row, "fiftytwowkpercentchange")
        href = _text(symbol_node.get("href") if symbol_node else "")
        if (
            _SYMBOL_RE.fullmatch(symbol) is None
            or symbol in seen_symbols
            or not name
            or price is None
            or price < 0
            or change is None
            or volume is None
            or volume < 0
            or href != f"/quote/{symbol}/"
        ):
            return []
        seen_symbols.add(symbol)
        url = f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/"
        data.append(
            ListItem(
                id=symbol,
                title=f"{symbol} · {name}",
                desc=_quote_description(
                    price,
                    change,
                    volume,
                    average_volume,
                    market_cap,
                    week_change,
                    None,
                ),
                hot=_table_hot(board_type, change, volume, week_change),
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _quote_description(
    price: float,
    change: float,
    volume: int,
    average_volume: int | None,
    market_cap: int | None,
    week_change: float | None,
    trending_score: float | None,
) -> str:
    parts = [
        f"现价 {_decimal(price)}",
        f"当日涨跌 {change:+.2f}%",
        f"成交量 {_compact_number(volume)}",
    ]
    if average_volume is not None:
        parts.append(f"3 月日均量 {_compact_number(average_volume)}")
    if market_cap is not None:
        parts.append(f"市值 {_compact_number(market_cap)}")
    if week_change is not None:
        parts.append(f"52 周涨跌 {week_change:+.2f}%")
    if trending_score is not None:
        parts.append(f"趋势分 {trending_score:.2f}")
    return " · ".join(parts)


def _table_hot(
    board_type: str,
    change: float,
    volume: int,
    week_change: float | None,
) -> int | None:
    if board_type == "trending":
        return None
    if board_type == "most-active":
        return volume
    score = week_change if board_type.startswith("52-week") else change
    return round(abs(score) * 100) if score is not None else None


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _decimal(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _parse_compact_cell(row: object, cell_name: str) -> int | None:
    if not hasattr(row, "select_one"):
        return None
    node = row.select_one(f"td[data-testid-cell='{cell_name}']")
    text = _text(node.get_text(" ", strip=True) if node else "").replace(",", "")
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([KMBT]?)", text)
    if match is None:
        return None
    multipliers = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
    }
    return round(float(match.group(1)) * multipliers[match.group(2)])


def _parse_percent_cell(row: object, cell_name: str) -> float | None:
    if not hasattr(row, "select_one"):
        return None
    node = row.select_one(f"td[data-testid-cell='{cell_name}']")
    text = _text(node.get_text(" ", strip=True) if node else "")
    return _number(text.removesuffix("%")) if text.endswith("%") else None


def _compact_number(value: int) -> str:
    units = (
        ("T", 1_000_000_000_000),
        ("B", 1_000_000_000),
        ("M", 1_000_000),
        ("K", 1_000),
    )
    for unit, divisor in units:
        if abs(value) >= divisor:
            return f"{value / divisor:.2f}{unit}"
    return f"{value:,}"
