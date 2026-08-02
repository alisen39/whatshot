from __future__ import annotations

import json
import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_strings,
    content_status,
    metrics,
    strip_html,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "sina-finance"

list_type: dict[str, dict[str, str]] = {
    "all": {"name": "全部", "tag": "0"},
    "a-share": {"name": "A股", "tag": "10"},
    "macro": {"name": "宏观", "tag": "1"},
    "company": {"name": "公司", "tag": "3"},
    "data": {"name": "数据", "tag": "4"},
    "market": {"name": "市场", "tag": "5"},
    "intl": {"name": "国际", "tag": "102"},
    "opinion": {"name": "观点", "tag": "6"},
    "central-bank": {"name": "央行", "tag": "7"},
    "other": {"name": "其他", "tag": "8"},
}

hot_stock_type: dict[str, dict[str, str]] = {
    "hot-stock-cn": {"name": "A股热搜", "market": "cn"},
    "hot-stock-hk": {"name": "港股热搜", "market": "hk"},
    "hot-stock-us": {"name": "美股热搜", "market": "us"},
    "hot-stock-fx": {"name": "外汇热搜", "market": "wh"},
    "hot-stock-futures": {"name": "期货热搜", "market": "ft"},
}

type_map = {
    **{key: value["name"] for key, value in list_type.items()},
    **{key: value["name"] for key, value in hot_stock_type.items()},
}

SOURCE_LINK = "https://finance.sina.com.cn/7x24/"

ROUTE_META: dict = {
    "name": "sina-finance",
    "title": "新浪财经",
    "description": "新浪财经 7x24 小时实时快讯",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
    "link": SOURCE_LINK,
}

_WAN_RE = re.compile(r"([\d.]+)\s*万")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "all")
    is_hot_stock = type_param in hot_stock_type
    if is_hot_stock:
        list_data = await _get_hot_stocks(type_param, no_cache)
        type_label = hot_stock_type[type_param]["name"]
    else:
        list_data = await _get_list(type_param, no_cache)
        type_label = list_type.get(type_param, list_type["all"])["name"]
    return RouterData(
        kind="hotlist" if is_hot_stock else "newsflash",
        **{**ROUTE_META, "type": type_label},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    type_info = list_type.get(type_param, list_type["all"])
    tag = type_info["tag"]
    url = "https://app.cj.sina.com.cn/api/news/pc"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "page": "1",
            "size": "50",
            "tag": tag,
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )

    raw = result.data or {}
    items = (((raw.get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    data: list[NewsFlashItem] = []
    for it in items:
        content = strip_html(it.get("rich_text") or "").strip()
        if not content:
            continue
        ext = _parse_ext(it.get("ext"))
        title = _derive_title(content)
        url = it.get("docurl") or ext.get("docurl") or SOURCE_LINK
        top_value = to_int(it.get("top_value"))
        data.append(
            NewsFlashItem(
                id=str(it.get("id") or f"sina-finance-{len(data)}"),
                title=title,
                content=content,
                contentStatus=content_status(content),
                source="新浪财经",
                isImportant=truthy_flag(it.get("is_focus")) or bool(top_value and top_value > 0),
                tags=compact_strings(it.get("tag")),
                symbols=compact_objects(ext.get("stocks")) + compact_objects(ext.get("terms")),
                metrics=metrics(
                    viewCount=_parse_views(it.get("view_num")),
                    commentCount=to_int(it.get("comment_num")),
                    likeCount=to_int(it.get("like_nums")),
                    topValue=top_value,
                ),
                timestamp=get_time(it.get("create_time")),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_hot_stocks(type_param: str, no_cache: bool) -> dict:
    market = hot_stock_type[type_param]["market"]
    result = await get(
        url=(
            "https://quotes.sina.cn/cn/api/openapi.php/"
            "StockSelectionService.getHotStocks"
        ),
        no_cache=no_cache,
        response_type="json",
        params={
            "market": market,
            "num": "10",
            "pageSize": "10",
            "page": "1",
            "type": "d",
            "version": "9.5.0.1",
        },
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    rows = ((result.data or {}).get("result") or {}).get("data") or []
    data: list[ListItem] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        item_market = str(row.get("market") or market)
        title = str(row.get("name") or symbol).strip()
        news = row.get("news") if isinstance(row.get("news"), dict) else {}
        desc_parts = [symbol]
        if news.get("title"):
            desc_parts.append(str(news["title"]))
        if row.get("fund_txt"):
            desc_parts.append(str(row["fund_txt"]))
        rank_change = _to_signed_int(row.get("uv_rank_chg"))
        if rank_change:
            desc_parts.append(f"排名变化：{rank_change:+d}")
        url = _stock_url(item_market, symbol)
        data.append(
            ListItem(
                id=f"{item_market}:{symbol}",
                title=title,
                desc=" · ".join(desc_parts),
                hot=to_int(row.get("pv")),
                timestamp=get_time(row.get("uptime")),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _stock_url(market: str, symbol: str) -> str:
    if market == "cn":
        return f"https://quotes.sina.cn/hs/company/quotes/view/{symbol}"
    if market == "hk":
        return f"https://quotes.sina.cn/hk/company/quotes/view/{symbol}"
    if market == "us":
        return f"https://gu.sina.cn/quotes/us/{symbol}"
    if market in {"global", "commodity"}:
        prefix, _, code = symbol.partition("_")
        return f"https://gu.sina.cn/ft/hq/{prefix}.php?symbol={code or symbol}"
    return f"https://gu.sina.cn/quotes/fx/{symbol}"


def _to_signed_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_views(value: object) -> int | None:
    if value is None:
        return None
    text = str(value)
    m = _WAN_RE.search(text)
    if m:
        try:
            return int(float(m.group(1)) * 10000)
        except ValueError:
            return None
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def _derive_title(content: str) -> str:
    if content.startswith("【"):
        end = content.find("】", 1)
        if 1 < end <= 80:
            return content[1:end]
    return content[:60] + ("..." if len(content) > 60 else "")


def _parse_ext(value: object) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
