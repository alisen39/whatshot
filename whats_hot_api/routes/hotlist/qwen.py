from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.routes.hotlist import qwen_research
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qwen"

SOURCE_LINK = "https://qwen.ai/research"

type_map: dict[str, str] = {
    "research": "研究与发布",
    "legacy-blog": "历史博客",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Qwen",
    "description": "Qwen 官方研究、模型发布与历史博客",
    "params": {
        "type": {
            "name": "内容分类",
            "type": type_map,
        },
    },
    "link": SOURCE_LINK,
}

_LEGACY_RSS_URL = "https://qwenlm.github.io/blog/index.xml"
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "research")
    selected = requested if requested in type_map else "research"
    list_data = (
        await qwen_research._get_list(no_cache)
        if selected == "research"
        else await _get_legacy_blog(no_cache)
    )
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_legacy_blog(no_cache: bool) -> dict:
    result = await get(
        url=_LEGACY_RSS_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": "https://qwenlm.github.io/blog/",
        },
        cache_key=f"qwen:legacy-blog:latest:{_MAX_ITEMS}",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_legacy_blog(result.data),
    }


def _parse_legacy_blog(xml_text: str) -> list[ListItem]:
    root = ET.fromstring(xml_text)
    items: list[ListItem] = []
    seen: set[str] = set()
    for node in root.findall("./channel/item"):
        title = _xml_text(node, "title")
        url = _xml_text(node, "link")
        slug = _blog_slug(url)
        timestamp = _rfc822_ms(_xml_text(node, "pubDate"))
        if not title or not slug or timestamp is None or slug in seen:
            continue
        seen.add(slug)
        items.append(
            ListItem(
                id=slug,
                title=title,
                author="Qwen Team",
                desc=_summary(_xml_text(node, "description")),
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


def _blog_slug(url: str) -> str | None:
    match = re.fullmatch(
        r"https://qwenlm\.github\.io/blog/([a-z0-9][a-z0-9.-]*)/?",
        url,
    )
    return match.group(1) if match else None


def _summary(value: str) -> str | None:
    text = BeautifulSoup(value, "lxml").get_text(" ", strip=True)
    return text[:240] or None


def _rfc822_ms(value: str) -> int | None:
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
