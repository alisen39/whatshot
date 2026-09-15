from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

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
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("OpenAI news RSS channel is missing")
    items = root.findall("./channel/item")
    parsed = sorted(
        items,
        key=lambda item: _rfc822_ms(_xml_text(item, "pubDate")) or 0,
        reverse=True,
    )
    data: list[ListItem] = []
    seen: set[str] = set()
    for item in parsed:
        title = _xml_text(item, "title")
        url = _xml_text(item, "link")
        if not title or not url:
            continue
        item_id = _slug(url)
        if item_id in seen:
            continue
        seen.add(item_id)
        data.append(
            ListItem(
                id=item_id,
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


def _slug(url: str) -> str:
    parsed = urlsplit(url)
    # Retain existing IDs for ordinary /index/<slug> articles; nested paths
    # need their full identity (e.g. NVIDIA and Virgin Atlantic /chatgpt-work).
    match = re.fullmatch(r"/index/([^/]+)/?", parsed.path)
    if match and parsed.hostname == "openai.com":
        return match.group(1)
    return parsed._replace(path=parsed.path.rstrip("/"), query="", fragment="").geturl()


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
