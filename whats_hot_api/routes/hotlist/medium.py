from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "medium"

SOURCE_LINK = "https://medium.com/tag/technology"
FEED_URL = "https://medium.com/feed/tag/technology"
_MEDIUM_ID_RE = re.compile(r"^https://medium\.com/p/([0-9a-f]{12})$")

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Medium",
    "description": "Medium Technology tag's latest public articles",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Technology",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_feed(result.data or ""),
    }


def _parse_feed(xml: str) -> list[ListItem]:
    root = ET.fromstring(xml)
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for item in root.findall("./channel/item"):
        article_id = _article_id(_xml_text(item, "guid"))
        title = _xml_text(item, "title")
        if not article_id or not title or article_id in seen_ids:
            continue
        seen_ids.add(article_id)
        description = _plain_text(_xml_text(item, "description"))
        author = _xml_text(item, "{http://purl.org/dc/elements/1.1/}creator")
        data.append(
            ListItem(
                id=article_id,
                title=title,
                url=f"https://medium.com/p/{article_id}",
                mobileUrl=f"https://medium.com/p/{article_id}",
                author=author or None,
                desc=description or None,
                timestamp=_rfc822_ms(_xml_text(item, "pubDate")),
            )
        )
    return data


def _xml_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _article_id(value: str) -> str | None:
    match = _MEDIUM_ID_RE.fullmatch(value.strip())
    return match.group(1) if match else None


def _plain_text(value: str) -> str:
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
