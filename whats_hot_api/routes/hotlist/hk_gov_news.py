from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hk-gov-news"

# 香港政府新闻网官方 RSS 的简体版:政府繁简转换站 sc.news.gov.hk/TuniS/ 前缀 + 繁体 RSS 路径
# (RSS 目录 /jsp/rssInfo.jsp?language=chi 列出的地址)。条目链接与 tophub 逐字同形,标题已转简体。
# RSS 与栏目页是同一份列表(栏目页脚本读的 JSP 列表与 RSS 逐条相同、顺序相同,board_api 已核对)。
_SC = "https://sc.news.gov.hk/TuniS/www.news.gov.hk"

type_map: dict[str, str] = {
    "topstories": "重要新闻",
    "ticker": "新闻速递",
    "feature": "特写",
    "record": "政府评论",
    "city-life": "都会生活",
    "admin": "行政与公民事务",
    "finance": "财经",
    "school-work": "教育与就业",
    "health": "社区与健康",
    "environment": "环境",
    "law-order": "治安",
    "infrastructure": "基建与物流",
    "nationalsecurity": "维护国家安全",
    "clarification": "政府澄清",
}

# 子榜 -> (RSS 路径, 栏目页路径)。普通类别的 RSS 在 /tc/categories/<类别>/html/ 下。
_FEED_PATHS: dict[str, str] = {
    "topstories": "/tc/common/html/topstories.rss.xml",
    "ticker": "/tc/common/html/ticker.rss.xml",
    "feature": "/tc/feature/index.rss.xml",
    "record": "/tc/record/html/articlelist.rss.xml",
    "city-life": "/tc/city_life/html/articlelist.rss.xml",
    "admin": "/tc/categories/admin/html/articlelist.rss.xml",
    "finance": "/tc/categories/finance/html/articlelist.rss.xml",
    "school-work": "/tc/categories/school_work/html/articlelist.rss.xml",
    "health": "/tc/categories/health/html/articlelist.rss.xml",
    "environment": "/tc/categories/environment/html/articlelist.rss.xml",
    "law-order": "/tc/categories/law_order/html/articlelist.rss.xml",
    "infrastructure": "/tc/categories/infrastructure/html/articlelist.rss.xml",
    "nationalsecurity": "/tc/categories/nationalsecurity/html/articlelist.rss.xml",
    "clarification": "/tc/categories/clarification/html/articlelist.rss.xml",
}
_PAGE_PATHS: dict[str, str] = {
    "topstories": "/chi/index.html",
    "ticker": "/chi/index.html",
    "feature": "/chi/feature/index.html",
    "record": "/chi/categories/record/index.html",
    "city-life": "/chi/categories/city_life/index.html",
    "admin": "/chi/categories/admin/index.html",
    "finance": "/chi/categories/finance/index.html",
    "school-work": "/chi/categories/school_work/index.html",
    "health": "/chi/categories/health/index.html",
    "environment": "/chi/categories/environment/index.html",
    "law-order": "/chi/categories/law_order/index.html",
    "infrastructure": "/chi/categories/infrastructure/index.html",
    "nationalsecurity": "/chi/categories/nationalsecurity/index.html",
    "clarification": "/chi/categories/clarification/index.html",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "香港政府新闻网",
    "description": "香港政府新闻网(简体)各栏目:重要新闻、新闻速递、特写、政府评论与各新闻类别。",
    "link": f"{_SC}/chi/",
    "params": {
        "type": {
            "name": "栏目",
            "type": type_map,
        },
    },
}

_HKT = timezone(timedelta(hours=8))
_ARTICLE_ID = re.compile(r"/(\d{8})_(\d{6})_\d{3}\.html")
_ACCEPT = "application/rss+xml, application/xml;q=0.9, */*;q=0.8"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "topstories")
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    result = await get(
        url=f"{_SC}{_FEED_PATHS[board]}",
        headers={"Accept": _ACCEPT},
        no_cache=no_cache,
        response_type="text",
    )
    items = _parse_items(str(result.data))
    if not items:
        raise RuntimeError(f"hk-gov-news {board} RSS produced no items (empty or non-feed response)")
    return RouterData(
        **{**ROUTE_META, "link": f"{_SC}{_PAGE_PATHS[board]}"},
        type=type_map[board],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _parse_items(xml: str) -> list[ListItem]:
    """按 feed 原顺序解析(顺序是网站的编辑顺序,同一天内不严格按时间,不重排)。"""
    soup = BeautifulSoup(xml, "xml")
    items: list[ListItem] = []
    for node in soup.find_all("item"):
        title = _tag_text(node, "title")
        url = _feed_link(node)
        if not title or not url.startswith(("http://", "https://")):
            continue
        description = _tag_text(node, "description")
        items.append(
            ListItem(
                id=_tag_text(node, "guid") or url,
                title=title,
                url=url,
                mobileUrl=url,
                cover=_feed_cover(node, description),
                desc=_clean_html(description),
                timestamp=_item_timestamp(url, _pubdate_seconds(_tag_text(node, "pubDate"))),
            )
        )
    return items


def _item_timestamp(url: str, pub_seconds: int | None) -> int | None:
    """RSS 的 pubDate 只到日(文章在网站上的日期);链接里的稿件编号 YYYYMMDD_HHMMSS 是香港时间。

    两者同一天时用稿件编号的时分秒(精确到秒);不同天时(特写这类先写好、隔几天才上的稿件)
    用 pubDate,不把稿件编号的日期当发布日期。
    """
    if pub_seconds is None:
        matched = _ARTICLE_ID.search(url)
        if matched is None:
            return None
        stamp = datetime.strptime(matched.group(1) + matched.group(2), "%Y%m%d%H%M%S").replace(tzinfo=_HKT)
        return get_time(int(stamp.timestamp()))
    pub_day = datetime.fromtimestamp(pub_seconds, _HKT).date()
    matched = _ARTICLE_ID.search(url)
    if matched is not None:
        stamp = datetime.strptime(matched.group(1) + matched.group(2), "%Y%m%d%H%M%S").replace(tzinfo=_HKT)
        if stamp.date() == pub_day:
            return get_time(int(stamp.timestamp()))
    return get_time(pub_seconds)


def _pubdate_seconds(value: Any) -> int | None:
    try:
        seconds = int(parsedate_to_datetime(str(value or "").strip()).timestamp())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return seconds if seconds > 0 else None


def _feed_link(node: Tag) -> str:
    link = node.find("link")
    if not link:
        return ""
    href = link.get("href")
    if isinstance(href, str) and href:
        return href.strip()
    return link.get_text("", strip=True)


def _feed_cover(node: Tag, description: str) -> str | None:
    enclosure = node.find("enclosure")
    if enclosure:
        candidate = enclosure.get("url")
        media_type = enclosure.get("type") or ""
        if (not media_type or str(media_type).startswith("image/")) and _valid_url(candidate):
            return str(candidate)
    image = BeautifulSoup(description or "", "lxml").find("img")
    candidate = image.get("src") if image else None
    return candidate if _valid_url(candidate) else None


def _tag_text(node: Tag, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _clean_html(value: Any, *, limit: int = 500) -> str | None:
    text = BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized[:limit] or None


def _valid_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))
