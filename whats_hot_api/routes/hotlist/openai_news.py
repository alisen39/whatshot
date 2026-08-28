from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "openai-news"

SOURCE_LINK = "https://openai.com/news"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OpenAI News",
    "description": "Official OpenAI product, research, and company updates",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"news": "News"},
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="News",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://openai.com/news/rss.xml",
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )

    root = ET.fromstring(result.data)
    items = root.findall("./channel/item")
    parsed = sorted(
        items,
        key=lambda item: _rfc822_ms(_xml_text(item, "pubDate")) or 0,
        reverse=True,
    )[:50]
    data: list[ListItem] = []
    for item in parsed:
        title = _xml_text(item, "title")
        url = _xml_text(item, "link")
        if not title or not url:
            continue
        data.append(
            ListItem(
                id=_slug(url) or url,
                title=title,
                desc=_summary(_xml_text(item, "description")),
                author=_xml_text(item, "category") or "OpenAI",
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


def _xml_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _summary(value: str) -> str | None:
    text = BeautifulSoup(value, "lxml").get_text(" ", strip=True)
    return text[:240] or None


def _slug(url: str) -> str | None:
    match = re.search(r"/([^/]+)/?$", url)
    return match.group(1) if match else None


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
