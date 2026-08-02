from __future__ import annotations

import re
from defusedxml import ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "chongbuluo"

SOURCE_LINK = "https://www.chongbuluo.com/"

list_type: dict[str, str] = {
    "hot": "热门",
    "latest": "最新",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "虫部落",
    "description": "虫部落社区帖子",
    "params": {
        "type": {
            "name": "榜单类型",
            "type": list_type,
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **{**ROUTE_META, "type": list_type.get(type_param, list_type["hot"])},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    if type_param == "latest":
        return await _get_latest(no_cache)
    return await _get_hot(no_cache)


async def _get_hot(no_cache: bool) -> dict:
    result = await get(
        url=urljoin(SOURCE_LINK, "forum.php?mod=guide&view=hot"),
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": SOURCE_LINK,
        },
    )

    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    for row in soup.select(".bmw table tr"):
        title_el = row.select_one(".common a.xst")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href") or ""
        url = urljoin(SOURCE_LINK, href)
        replies = _to_int(row.select_one("td.num a.xi2"))
        views = _to_int(row.select_one("td.num em"))
        last_time_el = row.select_one("td.by span[title]") or row.select_one("td.by span")
        author_el = row.select_one("td.by cite a")
        participant_el = row.select_one(".common .xi1")
        data.append(
            ListItem(
                id=_thread_id(url) or url,
                title=title,
                author=author_el.get_text(strip=True) if author_el else None,
                desc=participant_el.get_text(strip=True) if participant_el else None,
                hot=(replies or 0) + (views or 0) or None,
                timestamp=_time_from_hot_cell(last_time_el),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_latest(no_cache: bool) -> dict:
    result = await get(
        url=urljoin(SOURCE_LINK, "forum.php?mod=rss&view=newthread"),
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )

    data: list[ListItem] = []
    root = ET.fromstring(result.data)
    for item in root.findall("./channel/item"):
        title = _xml_text(item, "title")
        url = _xml_text(item, "link")
        if not title or not url:
            continue
        data.append(
            ListItem(
                id=_thread_id(url) or url,
                title=title,
                author=_xml_text(item, "author") or None,
                desc=_strip_xml_desc(_xml_text(item, "description")) or None,
                timestamp=_rfc822_ms(_xml_text(item, "pubDate")),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _to_int(node) -> int | None:  # noqa: ANN001
    if not node:
        return None
    match = re.search(r"\d+", node.get_text("", strip=True))
    return int(match.group(0)) if match else None


def _thread_id(url: str) -> str | None:
    match = re.search(r"thread-(\d+)-", url)
    return match.group(1) if match else None


def _time_from_hot_cell(node) -> int | None:  # noqa: ANN001
    if not node:
        return None
    text = node.get("title") or node.get_text(" ", strip=True)
    return get_time(text)


def _xml_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _strip_xml_desc(value: str) -> str:
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
