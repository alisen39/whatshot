from __future__ import annotations

import math
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "defillama"

SOURCE_LINK = "https://defillama.com/protocols"
_PROTOCOLS_URL = "https://api.llama.fi/protocols"
_MAX_ITEMS = 100
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "DefiLlama",
    "description": "DefiLlama 协议总锁仓价值（TVL）排行榜",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="协议 TVL 排行榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_PROTOCOLS_URL,
        no_cache=no_cache,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = result.data if isinstance(result.data, list) else []
    ranked = sorted(
        (row for row in rows if _is_rankable(row)),
        key=lambda row: _number(row.get("tvl")) or 0,
        reverse=True,
    )[:_MAX_ITEMS]
    data = [
        item
        for rank, row in enumerate(ranked, start=1)
        if (item := _protocol_item(row, rank)) is not None
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _is_rankable(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    slug = str(row.get("slug") or "").strip()
    name = str(row.get("name") or "").strip()
    tvl = _number(row.get("tvl"))
    return bool(name and _SLUG_PATTERN.fullmatch(slug) and tvl is not None and tvl >= 0)


def _protocol_item(row: dict, rank: int) -> ListItem | None:
    if not _is_rankable(row):
        return None

    slug = str(row["slug"]).strip()
    name = str(row["name"]).strip()
    symbol = str(row.get("symbol") or "").strip()
    tvl = _number(row.get("tvl"))
    if tvl is None:
        return None

    title = f"{name} ({symbol})" if symbol and symbol != "-" else name
    category = str(row.get("category") or "").strip()
    chains = [
        str(chain).strip()
        for chain in row.get("chains") or []
        if str(chain).strip()
    ]

    desc_parts = [f"排名：{rank}", f"TVL：${_money(tvl)}"]
    if category:
        desc_parts.append(f"分类：{category}")
    if (change_1d := _number(row.get("change_1d"))) is not None:
        desc_parts.append(f"24h：{change_1d:+.2f}%")
    if (change_7d := _number(row.get("change_7d"))) is not None:
        desc_parts.append(f"7d：{change_7d:+.2f}%")
    if (mcap := _number(row.get("mcap"))) is not None:
        desc_parts.append(f"市值：${_money(mcap)}")
    if chains:
        shown_chains = "、".join(chains[:8])
        if len(chains) > 8:
            shown_chains += f" 等 {len(chains)} 条链"
        desc_parts.append(f"链：{shown_chains}")

    url = f"https://defillama.com/protocol/{slug}"
    return ListItem(
        id=slug,
        title=title,
        desc=" · ".join(desc_parts),
        hot=round(tvl),
        cover=str(row.get("logo") or "").strip() or None,
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
