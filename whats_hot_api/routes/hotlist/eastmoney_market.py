from __future__ import annotations

import math
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "eastmoney-market"

SOURCE_LINK = "https://quote.eastmoney.com/center/"
_API_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
_CAIFUHAO_URL = "https://caifuhao.eastmoney.com/hot"
_DRAGON_TIGER_PAGE_URL = "https://data.eastmoney.com/stock/tradedetail.html"
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_BOARD_CHANGES_URL = "https://push2ex.eastmoney.com/getAllBKChanges"
_LEGACY_A_SHARE_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
_MARKETS: dict[str, tuple[str, str]] = {
    "hs-a": ("沪深 A 股", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"),
    "sh-a": ("沪市 A 股", "m:1+t:2,m:1+t:23"),
    "sz-a": ("深市 A 股", "m:0+t:6,m:0+t:80"),
    "bj-a": ("北证 A 股", "m:0+t:81+s:2048"),
    "cyb": ("创业板", "m:0+t:80"),
    "kcb": ("科创板", "m:1+t:23"),
    "hk": ("港股", "m:116+t:3,m:116+t:4,m:116+t:1,m:116+t:2"),
    "us": ("美股", "m:105,m:106,m:107"),
}

_SORTS: dict[str, tuple[str, str, str]] = {
    "change": ("涨幅榜", "f3", "1"),
    "drop": ("跌幅榜", "f3", "0"),
    "turnover": ("成交额榜", "f6", "1"),
    "volume": ("成交量榜", "f5", "1"),
    "amplitude": ("振幅榜", "f7", "1"),
    "rate": ("换手率榜", "f8", "1"),
}

type_map: dict[str, dict[str, str]] = {
    "gainers": {
        "name": "A股涨幅榜",
        "field": "f3",
        "order": "1",
        "filter": _LEGACY_A_SHARE_FILTER,
    },
    "losers": {
        "name": "A股跌幅榜",
        "field": "f3",
        "order": "0",
        "filter": _LEGACY_A_SHARE_FILTER,
    },
    "main-inflow": {
        "name": "主力净流入榜",
        "field": "f62",
        "order": "1",
        "filter": _LEGACY_A_SHARE_FILTER,
    },
}

_CAIFUHAO_TYPES = {
    "discussion-stock": "24H 讨论热股",
    "hot-topic": "热门话题",
}

_DRAGON_TIGER_TYPES = {
    "dragon-tiger-1d": ("龙虎榜 · 当日", "1"),
    "dragon-tiger-3d": ("龙虎榜 · 近3日", "3"),
    "dragon-tiger-5d": ("龙虎榜 · 近5日", "5"),
    "dragon-tiger-10d": ("龙虎榜 · 近10日", "10"),
    "dragon-tiger-30d": ("龙虎榜 · 近30日", "30"),
}

_BOARD_CHANGE_TYPES = {
    "board-change-count": ("板块异动 · 次数榜", "ct"),
    "board-change-rate": ("板块异动 · 涨幅榜", "u"),
    "board-change-funds": ("板块异动 · 主力资金榜", "zjl"),
}

_SECTOR_FLOW_TYPES = {
    "concept-flow-today": (
        "概念板块资金 · 今日",
        "m:90+t:3",
        "f62",
        "f3",
        "f184",
        "f204",
        "f205",
    ),
    "concept-flow-5d": (
        "概念板块资金 · 5日",
        "m:90+t:3",
        "f164",
        "f109",
        "f165",
        "f257",
        "f258",
    ),
    "concept-flow-10d": (
        "概念板块资金 · 10日",
        "m:90+t:3",
        "f174",
        "f160",
        "f175",
        "f260",
        "f261",
    ),
    "industry-flow-today": (
        "行业板块资金 · 今日",
        "m:90+s:4",
        "f62",
        "f3",
        "f184",
        "f204",
        "f205",
    ),
    "industry-flow-5d": (
        "行业板块资金 · 5日",
        "m:90+s:4",
        "f164",
        "f109",
        "f165",
        "f257",
        "f258",
    ),
    "industry-flow-10d": (
        "行业板块资金 · 10日",
        "m:90+s:4",
        "f174",
        "f160",
        "f175",
        "f260",
        "f261",
    ),
}

_DEPARTMENT_RETURN_TYPES = {
    "department-return-1m": ("营业部跟踪 · 近1月", "01"),
    "department-return-3m": ("营业部跟踪 · 近3月", "02"),
    "department-return-6m": ("营业部跟踪 · 近6月", "03"),
    "department-return-1y": ("营业部跟踪 · 近1年", "04"),
}

_ACTIVE_DEPARTMENT_TYPES = {
    "active-department-1d": ("活跃营业部 · 当日", "NEWDATE"),
    "active-department-3d": ("活跃营业部 · 近3日", "STARTDATE3"),
    "active-department-5d": ("活跃营业部 · 近5日", "STARTDATE5"),
    "active-department-10d": ("活跃营业部 · 近10日", "STARTDATE10"),
    "active-department-30d": ("活跃营业部 · 近30日", "STARTDATE30"),
}

_CHANGE_TYPE_LABELS = {
    1: "顶级买单",
    2: "顶级卖单",
    4: "封涨停板",
    8: "封跌停板",
    16: "打开涨停板",
    32: "打开跌停板",
    64: "有大买盘",
    128: "有大卖盘",
    256: "机构买单",
    512: "机构卖单",
    8193: "大笔买入",
    8194: "大笔卖出",
    8201: "火箭发射",
    8202: "快速反弹",
    8203: "高台跳水",
    8204: "加速下跌",
    8207: "竞价上涨",
    8208: "竞价下跌",
    8213: "60日新高",
    8214: "60日新低",
    8219: "放量上涨",
    8220: "放量下跌",
    8221: "缩量上涨",
    8222: "缩量下跌",
}

for _market_key, (_market_name, _market_filter) in _MARKETS.items():
    for _sort_key, (_sort_name, _field, _order) in _SORTS.items():
        if _market_key == "hs-a" and _sort_key in {"change", "drop"}:
            continue
        type_map[f"{_market_key}-{_sort_key}"] = {
            "name": f"{_market_name} · {_sort_name}",
            "field": _field,
            "order": _order,
            "filter": _market_filter,
        }

for _type_key, _type_name in _CAIFUHAO_TYPES.items():
    type_map[_type_key] = {"name": _type_name, "source": "caifuhao"}

for _type_key, (_type_name, _period) in _DRAGON_TIGER_TYPES.items():
    type_map[_type_key] = {
        "name": _type_name,
        "source": "dragon-tiger",
        "period": _period,
    }

for _type_key, (_type_name, _field) in _BOARD_CHANGE_TYPES.items():
    type_map[_type_key] = {
        "name": _type_name,
        "source": "board-changes",
        "field": _field,
    }

for _type_key, (_type_name, *_fields) in _SECTOR_FLOW_TYPES.items():
    type_map[_type_key] = {
        "name": _type_name,
        "source": "sector-flow",
    }

for _type_key, (_type_name, _cycle) in _DEPARTMENT_RETURN_TYPES.items():
    type_map[_type_key] = {
        "name": _type_name,
        "source": "department-return",
        "cycle": _cycle,
    }

for _type_key, (_type_name, _date_field) in _ACTIVE_DEPARTMENT_TYPES.items():
    type_map[_type_key] = {
        "name": _type_name,
        "source": "active-department",
        "date_field": _date_field,
    }

ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "东方财富行情",
    "description": "东方财富行情、板块资金、龙虎榜、营业部与社区热榜",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "行情榜单",
            "type": {key: value["name"] for key, value in type_map.items()},
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "gainers")
    selected_type = requested_type if requested_type in type_map else "gainers"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        kind="hotlist",
        **ROUTE_META,
        type=type_map[selected_type]["name"],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(selected_type: str, no_cache: bool) -> dict[str, Any]:
    if selected_type in _CAIFUHAO_TYPES:
        return await _get_caifuhao_list(selected_type, no_cache)
    if selected_type in _DRAGON_TIGER_TYPES:
        return await _get_dragon_tiger_list(selected_type, no_cache)
    if selected_type in _BOARD_CHANGE_TYPES:
        return await _get_board_change_list(selected_type, no_cache)
    if selected_type in _SECTOR_FLOW_TYPES:
        return await _get_sector_flow_list(selected_type, no_cache)
    if selected_type in _DEPARTMENT_RETURN_TYPES:
        return await _get_department_return_list(selected_type, no_cache)
    if selected_type in _ACTIVE_DEPARTMENT_TYPES:
        return await _get_active_department_list(selected_type, no_cache)

    board = type_map[selected_type]
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "pn": "1",
            "pz": "50",
            "np": "1",
            "fltt": "2",
            "fs": board["filter"],
            "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f8,f9,f10,f15,f16,f17,f18,f20,f21,f62,f184",
            "fid": board["field"],
            "po": board["order"],
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://quote.eastmoney.com/",
        },
    )

    items = ((result.data or {}).get("data") or {}).get("diff") or []
    data: list[ListItem] = []
    for item in items:
        code = _text(item.get("f12"))
        name = _text(item.get("f14"))
        market = _integer(item.get("f13"))
        if not code or not name or market is None:
            continue
        detail_url = f"https://quote.eastmoney.com/unify/r/{market}.{code}"
        data.append(
            ListItem(
                id=f"{market}.{code}",
                title=name,
                author=code,
                desc=_description(item),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_caifuhao_list(selected_type: str, no_cache: bool) -> dict[str, Any]:
    result = await get(
        url=_CAIFUHAO_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://caifuhao.eastmoney.com/",
        },
    )
    soup = BeautifulSoup(result.data or "", "lxml")
    data = (
        _parse_discussion_stocks(soup)
        if selected_type == "discussion-stock"
        else _parse_hot_topics(soup)
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_discussion_stocks(soup: BeautifulSoup) -> list[ListItem]:
    data: list[ListItem] = []
    for row in soup.select("#hot_stock ul.list_side > li.item"):
        link = row.select_one(".left a[href]")
        if not link:
            continue
        href = str(link.get("href") or "").strip()
        title = link.get_text(" ", strip=True)
        path_parts = [part for part in href.split("/") if part]
        code = path_parts[-2] if len(path_parts) >= 2 else None
        market = path_parts[-3] if len(path_parts) >= 3 else None
        hot_element = row.select_one(".right span")
        hot = _parse_compact_number(
            hot_element.get_text(strip=True) if hot_element else None
        )
        if not href or not title:
            continue
        url = urljoin(_CAIFUHAO_URL, href)
        data.append(
            ListItem(
                id=f"{market}.{code}" if market and code else href,
                title=title,
                author=code,
                hot=hot,
                desc=f"24H 讨论热度 {hot}" if hot is not None else "24H 讨论热度排行",
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _parse_hot_topics(soup: BeautifulSoup) -> list[ListItem]:
    data: list[ListItem] = []
    for row in soup.select(".hot_topic ul.topic_list > li.item"):
        link = row.select_one(".title a[href]")
        if not link:
            continue
        url = urljoin(_CAIFUHAO_URL, str(link.get("href") or "").strip())
        title = link.get_text(" ", strip=True)
        topic_id = (parse_qs(urlparse(url).query).get("htid") or [url])[0]
        info = row.select(".info span")
        reads_text = str(info[0].get("title") or info[0].get_text(strip=True)) if info else ""
        discussions_text = (
            str(info[1].get("title") or info[1].get_text(strip=True))
            if len(info) > 1
            else ""
        )
        reads = _parse_compact_number(reads_text)
        description_element = row.select_one(".desc")
        description = (
            description_element.get_text(" ", strip=True)
            if description_element
            else ""
        )
        metrics = []
        if reads_text:
            metrics.append(f"阅读 {reads_text}")
        if discussions_text:
            metrics.append(f"讨论 {discussions_text}")
        desc = "；".join([*metrics, description] if description else metrics) or None
        image = row.select_one(".img img[src]")
        cover = urljoin(_CAIFUHAO_URL, str(image.get("src"))) if image else None
        if not title or not url:
            continue
        data.append(
            ListItem(
                id=topic_id,
                title=title,
                hot=reads,
                desc=desc,
                cover=cover,
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _parse_compact_number(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    try:
        return round(float(text) * multiplier)
    except ValueError:
        return None


async def _get_dragon_tiger_list(
    selected_type: str, no_cache: bool
) -> dict[str, Any]:
    page_result = await get(
        url=_DRAGON_TIGER_PAGE_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
    )
    period = _DRAGON_TIGER_TYPES[selected_type][1]
    start_date, end_date = _dragon_tiger_dates(page_result.data or "", period)
    if not start_date or not end_date:
        return {
            "from_cache": page_result.from_cache,
            "update_time": page_result.update_time,
            "data": [],
        }

    result = await get(
        url=_DATACENTER_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "sortColumns": "BILLBOARD_NET_AMT,TRADE_DATE,SECURITY_CODE",
            "sortTypes": "-1,-1,1",
            "pageSize": "50",
            "pageNumber": "1",
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": (
                "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,"
                "CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,"
                "BILLBOARD_SELL_AMT,BILLBOARD_DEAL_AMT,ACCUM_AMOUNT,DEAL_NET_RATIO,"
                "DEAL_AMOUNT_RATIO,TURNOVERRATE,FREE_MARKET_CAP,EXPLANATION,"
                "D1_CLOSE_ADJCHRATE,D2_CLOSE_ADJCHRATE,D5_CLOSE_ADJCHRATE,"
                "D10_CLOSE_ADJCHRATE,SECURITY_TYPE_CODE"
            ),
            "source": "WEB",
            "client": "WEB",
            "filter": (
                f"(TRADE_DATE<='{end_date}')(TRADE_DATE>='{start_date}')"
            ),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": _DRAGON_TIGER_PAGE_URL,
        },
    )
    rows = ((result.data or {}).get("result") or {}).get("data") or []
    data: list[ListItem] = []
    for row in rows:
        code = _text(row.get("SECURITY_CODE"))
        name = _text(row.get("SECURITY_NAME_ABBR"))
        trade_date = _text(row.get("TRADE_DATE"))
        if not code or not name or not trade_date:
            continue
        date = trade_date[:10]
        detail_url = f"https://data.eastmoney.com/stock/lhb,{date},{code}.html"
        data.append(
            ListItem(
                id=f"{date}:{code}",
                title=name,
                author=code,
                hot=_integer(row.get("BILLBOARD_NET_AMT")),
                desc=_dragon_tiger_description(row, date),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _dragon_tiger_dates(html: str, period: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "lxml")
    start = soup.select_one(f'.day_type li[data-value="{period}"][date]')
    end = soup.select_one('.day_type li[data-value="1"][date]')
    return (
        str(start.get("date") or "").strip() or None if start else None,
        str(end.get("date") or "").strip() or None if end else None,
    )


def _dragon_tiger_description(row: dict[str, Any], date: str) -> str | None:
    parts = [f"上榜日 {date}"]
    change = _number(row.get("CHANGE_RATE"))
    net = _number(row.get("BILLBOARD_NET_AMT"))
    turnover = _number(row.get("TURNOVERRATE"))
    if change is not None:
        parts.append(f"涨跌幅 {change:+.2f}%")
    if net is not None:
        parts.append(f"龙虎榜净买额 {net / 100_000_000:+.2f} 亿元")
    if turnover is not None:
        parts.append(f"换手率 {turnover:.2f}%")
    reason = _text(row.get("EXPLANATION")) or _text(row.get("EXPLAIN"))
    if reason:
        parts.append(reason)
    return "；".join(parts)


async def _get_board_change_list(
    selected_type: str, no_cache: bool
) -> dict[str, Any]:
    result = await get(
        url=_BOARD_CHANGES_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wzchanges",
            "pageindex": "0",
            "pagesize": "2000",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://quote.eastmoney.com/changes/boardlist.html",
        },
    )
    rows = ((result.data or {}).get("data") or {}).get("allbk") or []
    field = _BOARD_CHANGE_TYPES[selected_type][1]
    rows = sorted(rows, key=lambda row: _number(row.get(field)) or 0, reverse=True)
    data: list[ListItem] = []
    for row in rows[:50]:
        code = _text(row.get("c"))
        name = _text(row.get("n"))
        market = _integer(row.get("m"))
        if not code or not name or market is None:
            continue
        detail_url = f"https://quote.eastmoney.com/bk/{market}.{code}.html"
        data.append(
            ListItem(
                id=code,
                title=name,
                hot=_board_change_hot(row, field),
                desc=_board_change_description(row),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_sector_flow_list(
    selected_type: str, no_cache: bool
) -> dict[str, Any]:
    (
        _,
        market_filter,
        flow_field,
        change_field,
        ratio_field,
        leader_field,
        leader_code_field,
    ) = _SECTOR_FLOW_TYPES[selected_type]
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "pn": "1",
            "pz": "50",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "ut": "8dec03ba335b81bf4ebdf7b29ec27d15",
            "fs": market_filter,
            "fid": flow_field,
            "po": "1",
            "fields": (
                "f12,f14,f2,f3,f62,f184,f109,f164,f165,f160,f174,f175,"
                "f204,f205,f257,f258,f260,f261,f124,f1,f13"
            ),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://data.eastmoney.com/bkzj/hy.html",
        },
    )
    rows = ((result.data or {}).get("data") or {}).get("diff") or []
    data: list[ListItem] = []
    for row in rows:
        code = _text(row.get("f12"))
        name = _text(row.get("f14"))
        if not code or not name:
            continue
        detail_url = f"https://data.eastmoney.com/bkzj/{code}.html"
        data.append(
            ListItem(
                id=f"90.{code}",
                title=name,
                author=code,
                hot=_integer(row.get(flow_field)),
                desc=_sector_flow_description(
                    row,
                    change_field,
                    ratio_field,
                    leader_field,
                    leader_code_field,
                ),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _sector_flow_description(
    row: dict[str, Any],
    change_field: str,
    ratio_field: str,
    leader_field: str,
    leader_code_field: str,
) -> str | None:
    parts: list[str] = []
    change = _number(row.get(change_field))
    ratio = _number(row.get(ratio_field))
    if change is not None:
        parts.append(f"区间涨跌幅 {change:+.2f}%")
    if ratio is not None:
        parts.append(f"主力净占比 {ratio:+.2f}%")
    leader = _text(row.get(leader_field))
    leader_code = _text(row.get(leader_code_field))
    if leader:
        parts.append(f"领涨股 {leader}" + (f"（{leader_code}）" if leader_code else ""))
    return "；".join(parts) or None


async def _get_department_return_list(
    selected_type: str, no_cache: bool
) -> dict[str, Any]:
    cycle = _DEPARTMENT_RETURN_TYPES[selected_type][1]
    result = await get(
        url=_DATACENTER_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "sortColumns": "TOTAL_BUYER_SALESTIMES_1DAY,OPERATEDEPT_CODE",
            "sortTypes": "-1,1",
            "pageSize": "50",
            "pageNumber": "1",
            "reportName": "RPT_RATEDEPT_RETURNT_RANKING",
            "columns": "ALL",
            "filter": f'(STATISTICSCYCLE="{cycle}")',
            "source": "WEB",
            "client": "WEB",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://data.eastmoney.com/stock/lhb.html",
        },
    )
    rows = ((result.data or {}).get("result") or {}).get("data") or []
    data: list[ListItem] = []
    for row in rows:
        code = _text(row.get("OPERATEDEPT_CODE"))
        name = _text(row.get("OPERATEDEPT_NAME"))
        if not code or not name:
            continue
        detail_url = f"https://data.eastmoney.com/stock/lhb/yyb/{code}.html"
        data.append(
            ListItem(
                id=code,
                title=name,
                hot=_integer(row.get("TOTAL_BUYER_SALESTIMES_1DAY")),
                desc=_department_return_description(row),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _department_return_description(row: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for days in (1, 3, 5, 10):
        average = _number(row.get(f"AVERAGE_INCREASE_{days}DAY"))
        probability = _number(row.get(f"RISE_PROBABILITY_{days}DAY"))
        if average is None and probability is None:
            continue
        metric = f"后{days}日"
        if average is not None:
            metric += f"均涨 {average:+.2f}%"
        if probability is not None:
            metric += f" / 上涨概率 {probability:.2f}%"
        parts.append(metric)
    return "；".join(parts) or None


async def _get_active_department_list(
    selected_type: str, no_cache: bool
) -> dict[str, Any]:
    date_result = await get(
        url=_DATACENTER_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "reportName": "RPT_ORGANIZATION_DATE",
            "columns": "ALL",
            "pageNumber": "1",
            "pageSize": "1",
            "source": "WEB",
            "client": "WEB",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://data.eastmoney.com/stock/hyyyb.html",
        },
    )
    date_rows = ((date_result.data or {}).get("result") or {}).get("data") or []
    date_field = _ACTIVE_DEPARTMENT_TYPES[selected_type][1]
    start_date = _text(date_rows[0].get(date_field)) if date_rows else None
    if not start_date:
        return {
            "from_cache": date_result.from_cache,
            "update_time": date_result.update_time,
            "data": [],
        }
    start_date = start_date[:10]
    result = await get(
        url=_DATACENTER_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "sortColumns": "TOTAL_NETAMT,ONLIST_DATE,OPERATEDEPT_CODE",
            "sortTypes": "-1,-1,1",
            "pageSize": "50",
            "pageNumber": "1",
            "reportName": "RPT_OPERATEDEPT_ACTIVE",
            "columns": "ALL",
            "filter": f"(ONLIST_DATE>='{start_date}')",
            "source": "WEB",
            "client": "WEB",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://data.eastmoney.com/stock/hyyyb.html",
        },
    )
    rows = ((result.data or {}).get("result") or {}).get("data") or []
    data: list[ListItem] = []
    for row in rows:
        code = _text(row.get("OPERATEDEPT_CODE"))
        name = _text(row.get("OPERATEDEPT_NAME"))
        listed_at = _text(row.get("ONLIST_DATE"))
        if not code or not name or not listed_at:
            continue
        date = listed_at[:10]
        detail_url = f"https://data.eastmoney.com/stock/lhb/yyb/{code}.html"
        data.append(
            ListItem(
                id=f"{date}:{code}",
                title=name,
                hot=_integer(row.get("TOTAL_NETAMT")),
                desc=_active_department_description(row, date),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _active_department_description(row: dict[str, Any], date: str) -> str:
    parts = [f"上榜日 {date}"]
    net = _number(row.get("TOTAL_NETAMT"))
    buy = _number(row.get("TOTAL_BUYAMT"))
    sell = _number(row.get("TOTAL_SELLAMT"))
    if net is not None:
        parts.append(f"净买额 {net / 100_000_000:+.2f} 亿元")
    if buy is not None and sell is not None:
        parts.append(
            f"买入 {buy / 100_000_000:.2f} 亿 / 卖出 {sell / 100_000_000:.2f} 亿"
        )
    buyer_count = _integer(row.get("BUYER_APPEAR_NUM"))
    seller_count = _integer(row.get("SELLER_APPEAR_NUM"))
    if buyer_count is not None and seller_count is not None:
        parts.append(f"买方 {buyer_count} 股 / 卖方 {seller_count} 股")
    return "；".join(parts)


def _board_change_hot(row: dict[str, Any], field: str) -> int | None:
    value = _number(row.get(field))
    if value is None:
        return None
    if field == "u":
        return round(value * 100)
    if field == "zjl":
        return round(value * 10_000)
    return round(value)


def _board_change_description(row: dict[str, Any]) -> str | None:
    parts: list[str] = []
    change = _number(row.get("u"))
    funds = _number(row.get("zjl"))
    count = _integer(row.get("ct"))
    if change is not None:
        parts.append(f"涨跌幅 {change:+.2f}%")
    if funds is not None:
        parts.append(f"主力资金 {funds / 10_000:+.2f} 亿元")
    if count is not None:
        parts.append(f"异动 {count} 次")
    max_stock = row.get("ms") if isinstance(row.get("ms"), dict) else {}
    stock_name = _text(max_stock.get("n"))
    change_type = _integer(max_stock.get("t"))
    if stock_name:
        label = _CHANGE_TYPE_LABELS.get(change_type or 0, f"异动 {change_type}")
        parts.append(f"最大异动股 {stock_name}（{label}）")
    return "；".join(parts) or None


def _description(item: dict[str, Any]) -> str | None:
    parts: list[str] = []
    price = _number(item.get("f2"))
    change_pct = _number(item.get("f3"))
    main_inflow = _number(item.get("f62"))
    main_ratio = _number(item.get("f184"))
    turnover = _number(item.get("f6"))

    if price is not None:
        parts.append(f"现价 {price:g} 元")
    if change_pct is not None:
        parts.append(f"涨跌幅 {change_pct:+.2f}%")
    if main_inflow is not None:
        parts.append(f"主力净流入 {main_inflow / 100_000_000:+.2f} 亿元")
    if main_ratio is not None:
        parts.append(f"净流入占比 {main_ratio:+.2f}%")
    if turnover is not None:
        parts.append(f"成交额 {turnover / 100_000_000:.2f} 亿元")
    return "；".join(parts) or None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and text != "-" else None


def _number(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
