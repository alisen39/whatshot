from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_strings,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
)
from whats_hot_api.utils.tokens.ths import generate_hexin_v

ROUTE_NAME = "ths-10jqka"

_INDUSTRY_FLOW_PERIODS: dict[str, str | None] = {
    "industry-flow-today": None,
    "industry-flow-3d": "3",
    "industry-flow-5d": "5",
    "industry-flow-10d": "10",
    "industry-flow-20d": "20",
}
_CONCEPT_FLOW_PERIODS: dict[str, str | None] = {
    "concept-flow-today": None,
    "concept-flow-3d": "3",
    "concept-flow-5d": "5",
    "concept-flow-10d": "10",
    "concept-flow-20d": "20",
}

type_map: dict[str, str] = {
    "quick": "快讯",
    "today": "财经要闻",
    "macro": "宏观经济",
    "industry": "产经新闻",
    "global": "国际财经",
    "market": "金融市场",
    "company": "公司新闻",
    "region": "区域经济",
    "comment": "财经评论",
    "people": "财经人物",
    "hot-stock": "热股榜",
    "industry-flow-today": "行业资金流 · 即时",
    "industry-flow-3d": "行业资金流 · 3日",
    "industry-flow-5d": "行业资金流 · 5日",
    "industry-flow-10d": "行业资金流 · 10日",
    "industry-flow-20d": "行业资金流 · 20日",
    "concept-flow-today": "概念资金流 · 即时",
    "concept-flow-3d": "概念资金流 · 3日",
    "concept-flow-5d": "概念资金流 · 5日",
    "concept-flow-10d": "概念资金流 · 10日",
    "concept-flow-20d": "概念资金流 · 20日",
}

_NEWS_LIST_PATHS: dict[str, str] = {
    "today": "today_list",
    "macro": "cjzx_list",
    "industry": "cjkx_list",
    "global": "guojicj_list",
    "market": "jrsc_list",
    "company": "fssgsxw_list",
    "region": "region_list",
    "comment": "fortune_list",
    "people": "cjrw_list",
}

SOURCE_LINK = "https://news.10jqka.com.cn/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "同花顺",
    "description": "同花顺全球财经快讯",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "新闻分类",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "quick")
    selected_type = requested_type if requested_type in type_map else "quick"
    if selected_type == "quick":
        list_data = await _get_flash_list(no_cache)
    elif selected_type == "hot-stock":
        list_data = await _get_hot_stock(no_cache)
    elif selected_type in _INDUSTRY_FLOW_PERIODS:
        list_data = await _get_sector_flow(
            selected_type, no_cache, sector="industry"
        )
    elif selected_type in _CONCEPT_FLOW_PERIODS:
        list_data = await _get_sector_flow(
            selected_type, no_cache, sector="concept"
        )
    else:
        list_data = await _get_news_list(selected_type, no_cache)
    return RouterData(
        kind=(
            "hotlist"
            if selected_type == "hot-stock"
            or selected_type in _INDUSTRY_FLOW_PERIODS
            or selected_type in _CONCEPT_FLOW_PERIODS
            else "newsflash"
        ),
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_hot_stock(no_cache: bool) -> dict:
    url = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params={"stock_type": "a", "type": "day", "list_type": "normal"},
        cache_key=f"{url}?stock_type=a&type=day&list_type=normal",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://eq.10jqka.com.cn/",
        },
    )
    rows = ((result.data or {}).get("data") or {}).get("stock_list") or []
    data: list[ListItem] = []
    for row in rows:
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not code or not name:
            continue
        tags = row.get("tag") if isinstance(row.get("tag"), dict) else {}
        concept_tags = [
            str(tag).strip()
            for tag in tags.get("concept_tag", [])
            if str(tag).strip()
        ]
        desc_parts = []
        if row.get("rise_and_fall") is not None:
            desc_parts.append(f"涨跌幅：{float(row['rise_and_fall']):+.2f}%")
        if tags.get("popularity_tag"):
            desc_parts.append(str(tags["popularity_tag"]).strip())
        if concept_tags:
            desc_parts.append("概念：" + "、".join(concept_tags))
        item_url = f"https://stockpage.10jqka.com.cn/{code}/"
        data.append(
            ListItem(
                id=code,
                title=name,
                desc=" · ".join(desc_parts) or None,
                hot=row.get("rate"),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_sector_flow(
    selected_type: str,
    no_cache: bool,
    *,
    sector: str,
) -> dict[str, Any]:
    is_concept = sector == "concept"
    route_name = "gnzjl" if is_concept else "hyzjl"
    base_url = f"https://data.10jqka.com.cn/funds/{route_name}"
    periods = _CONCEPT_FLOW_PERIODS if is_concept else _INDUSTRY_FLOW_PERIODS
    period = periods[selected_type]
    headers = _sector_flow_headers(base_url)
    first_result = await get(
        url=(
            f"{base_url}/board/{period}/ajax/1/"
            if period
            else (
                f"{base_url}/field/tradezdf/order/desc/ajax/1/"
                if is_concept
                else f"{base_url}/ajax/1/"
            )
        ),
        no_cache=no_cache,
        response_type="text",
        headers=headers,
    )
    results = [first_result]
    for page in range(2, _page_count(first_result.data or "") + 1):
        results.append(
            await get(
                url=(
                    f"{base_url}/"
                    + (f"board/{period}/" if period else "")
                    + "field/tradezdf/order/desc/"
                    f"page/{page}/ajax/1/"
                ),
                no_cache=no_cache,
                response_type="text",
                headers=_sector_flow_headers(base_url),
            )
        )
    data: list[ListItem] = []
    for result in results:
        data.extend(
            _parse_sector_flow_rows(
                result.data or "",
                historical=period is not None,
                detail_segment="gn" if is_concept else "thshy",
            )
        )
    return {
        "from_cache": all(result.from_cache for result in results),
        "update_time": max(result.update_time for result in results),
        "data": data,
    }


def _sector_flow_headers(base_url: str) -> dict[str, str]:
    return {
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "hexin-v": generate_hexin_v(),
        "Pragma": "no-cache",
        "Referer": f"{base_url}/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }


def _parse_sector_flow_rows(
    html: str,
    *,
    historical: bool = False,
    detail_segment: str,
) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    data: list[ListItem] = []
    for row in soup.select("tbody tr"):
        cells = row.select("td")
        if len(cells) < (8 if historical else 11):
            continue
        link = cells[1].select_one(
            f'a[href*="/{detail_segment}/detail/code/"]'
        )
        title = cells[1].get_text(" ", strip=True)
        href = _https_url(link.get("href")) if link else None
        code_match = re.search(r"/code/(\d+)/?", href or "")
        if not title or not href or not code_match:
            continue

        if historical:
            company_count = to_int(cells[2].get_text(" ", strip=True))
            change = _percent(cells[4].get_text(" ", strip=True))
            inflow = _billions_to_yuan(cells[5].get_text(" ", strip=True))
            outflow = _billions_to_yuan(cells[6].get_text(" ", strip=True))
            net = _billions_to_yuan(cells[7].get_text(" ", strip=True))
            leader = ""
            leader_change = None
        else:
            change = _percent(cells[3].get_text(" ", strip=True))
            inflow = _billions_to_yuan(cells[4].get_text(" ", strip=True))
            outflow = _billions_to_yuan(cells[5].get_text(" ", strip=True))
            net = _billions_to_yuan(cells[6].get_text(" ", strip=True))
            company_count = to_int(cells[7].get_text(" ", strip=True))
            leader = cells[8].get_text(" ", strip=True)
            leader_change = _percent(cells[9].get_text(" ", strip=True))

        desc_parts: list[str] = []
        if change is not None:
            desc_parts.append(f"涨跌幅 {change:+.2f}%")
        if inflow is not None:
            desc_parts.append(f"流入 {inflow / 100_000_000:.2f} 亿元")
        if outflow is not None:
            desc_parts.append(f"流出 {outflow / 100_000_000:.2f} 亿元")
        if company_count is not None:
            desc_parts.append(f"{company_count} 家公司")
        if leader:
            leader_text = f"领涨股 {leader}"
            if leader_change is not None:
                leader_text += f"（{leader_change:+.2f}%）"
            desc_parts.append(leader_text)

        data.append(
            ListItem(
                id=code_match.group(1),
                title=title,
                hot=net,
                desc="；".join(desc_parts) or None,
                url=href,
                mobileUrl=href,
            )
        )
    return data


def _page_count(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    page_info = soup.select_one(".page_info")
    match = re.search(r"/(\d+)", page_info.get_text(" ", strip=True) if page_info else "")
    return max(1, int(match.group(1))) if match else 1


def _percent(value: object) -> float | None:
    text = str(value or "").strip().removesuffix("%")
    if not text or text == "--":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _billions_to_yuan(value: object) -> int | None:
    text = str(value or "").strip()
    if not text or text == "--":
        return None
    try:
        return round(float(text) * 100_000_000)
    except ValueError:
        return None


async def _get_flash_list(no_cache: bool) -> dict:
    url = "https://news.10jqka.com.cn/tapp/news/push/stock"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "page": "1",
            "tag": "21101",
            "track": "website",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    items = (result.data or {}).get("data", {}).get("list") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title"))
        content = strip_html(it.get("digest") or it.get("short") or title)
        if not title and not content:
            continue

        importance = to_int(it.get("import"))
        detail_url = text_or_none(it.get("url")) or SOURCE_LINK
        mobile_url = (
            text_or_none(it.get("appUrl"))
            or text_or_none(it.get("shareUrl"))
            or detail_url
        )
        data.append(
            NewsFlashItem(
                id=str(it.get("id") or it.get("seq") or f"ths-10jqka-{len(data)}"),
                title=title or content[:60],
                content=content,
                summary=content if content and content != title else None,
                contentStatus=content_status(content, fallback="summary"),
                source=text_or_none(it.get("source")) or "同花顺",
                isImportant=(importance or 0) >= 2,
                tags=_merge_tags(it.get("tag"), it.get("tags"), it.get("tagInfo")),
                images=compact_urls(it.get("picUrl")),
                symbols=compact_objects(it.get("stock")),
                metrics=metrics(
                    seq=to_int(it.get("seq")),
                    color=to_int(it.get("color")),
                    nature=to_int(it.get("nature")),
                    importance=importance,
                    fields=compact_objects(it.get("field")) or None,
                    topicTags=compact_strings(it.get("tagInfo")) or None,
                ),
                timestamp=get_time(it.get("rtime") or it.get("ctime")),
                url=detail_url,
                mobileUrl=mobile_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_news_list(selected_type: str, no_cache: bool) -> dict:
    path = _NEWS_LIST_PATHS[selected_type]
    url = f"https://news.10jqka.com.cn/{path}/"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": SOURCE_LINK,
        },
    )

    soup = BeautifulSoup(result.data or "", "lxml")
    data: list[NewsFlashItem] = []
    for row in soup.select(".list-con li"):
        title_node = row.select_one(".arc-title a")
        if title_node is None:
            continue
        title = title_node.get_text(" ", strip=True)
        detail_url = _https_url(title_node.get("href"))
        if not title or not detail_url:
            continue

        summary_node = row.select_one(".arc-cont")
        summary = summary_node.get_text(" ", strip=True) if summary_node else ""
        time_node = row.select_one(".arc-title span")
        published_at = time_node.get_text(" ", strip=True) if time_node else ""
        item_id = text_or_none(title_node.get("data-seq")) or detail_url
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=summary or title,
                summary=summary or None,
                contentStatus=content_status(summary or title, fallback="summary"),
                source="同花顺",
                tags=[type_map[selected_type]],
                timestamp=get_time(published_at),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _https_url(value: object) -> str | None:
    url = text_or_none(value)
    if not url:
        return None
    return f"https:{url}" if url.startswith("//") else re.sub(r"^http://", "https://", url)


def _merge_tags(*groups: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            values = re.split(r"[,，;；\s]+", group)
        else:
            values = compact_strings(group)
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
    return result
