from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "rfc"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "RFC Editor",
    "description": "RFC Editor 官方最近发布的 Internet 标准与技术文档",
    "link": "https://www.rfc-editor.org/",
}

_FEED_URL = "https://www.rfc-editor.org/rfcrss.xml"
_TITLE_RE = re.compile(r"^RFC\s+(\d+):\s*(.+)$", re.IGNORECASE)
_INFO_URL_RE = re.compile(
    r"^https://www\.rfc-editor\.org/info/rfc(\d+)/?$", re.IGNORECASE
)
_MAX_ITEMS = 30


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最近发布",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": "https://www.rfc-editor.org/",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_feed(result.data or ""),
    }


def _parse_feed(xml_text: str) -> list[ListItem]:
    root = ET.fromstring(xml_text)
    items: list[ListItem] = []
    seen_numbers: set[int] = set()

    for node in root.findall("./channel/item"):
        raw_title = _xml_text(node, "title")
        title_match = _TITLE_RE.fullmatch(raw_title)
        url = _xml_text(node, "link")
        url_match = _INFO_URL_RE.fullmatch(url)
        timestamp = _rfc822_ms(_xml_text(node, "pubDate"))
        if not title_match or not url_match or timestamp is None:
            continue

        title_number = int(title_match.group(1))
        url_number = int(url_match.group(1))
        if title_number != url_number or title_number in seen_numbers:
            continue

        seen_numbers.add(title_number)
        summary = _plain_text(_xml_text(node, "description"))
        items.append(
            ListItem(
                id=f"rfc{title_number}",
                title=raw_title,
                author="RFC Editor",
                desc=summary or None,
                timestamp=timestamp,
                url=url,
                mobileUrl=url,
            )
        )

    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items[:_MAX_ITEMS]


def _xml_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _plain_text(value: str) -> str:
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
