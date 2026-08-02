from __future__ import annotations

from datetime import datetime
from urllib.parse import unquote, urlparse

from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "reuters"

type_map: dict[str, str] = {
    "official": "官方最新",
    "google-news": "Google News 聚合",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Reuters",
    "description": "Reuters 官方最新发布与 Google News 近期收录",
    "params": {
        "type": {
            "name": "内容分类",
            "type": type_map,
        },
    },
    "link": "https://www.reuters.com/",
}

_GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q=site%3Areuters.com&hl=en-US&gl=US&ceid=US%3Aen"
_OFFICIAL_NEWS_SITEMAP = (
    "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"
)
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
_IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
_NON_ENGLISH_PREFIXES = frozenset({"de", "es", "fr", "ja", "pt"})
_MAX_ITEMS = 30


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "official")
    selected = requested if requested in type_map else "official"
    list_data = (
        await _get_official(no_cache)
        if selected == "official"
        else await _get_google_news(no_cache)
    )
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_official(no_cache: bool) -> dict:
    result = await get(
        url=_OFFICIAL_NEWS_SITEMAP,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/xml, text/xml",
            "Referer": "https://www.reuters.com/",
        },
        cache_key="reuters:official-news-sitemap",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_official_news_sitemap(result.data or ""),
    }


async def _get_google_news(no_cache: bool) -> dict:
    result = await get(url=_GOOGLE_NEWS_URL, no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/rss+xml,application/xml,text/xml"})
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)}


def _parse_official_news_sitemap(xml_text: str) -> list[ListItem]:
    root = ET.fromstring(xml_text)
    items: list[ListItem] = []
    seen_urls: set[str] = set()

    for node in root.findall(f"{{{_SITEMAP_NS}}}url"):
        url = _xml_text(node, f"{{{_SITEMAP_NS}}}loc")
        parsed = urlparse(url)
        path_parts = [unquote(part) for part in parsed.path.split("/") if part]
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"reuters.com", "www.reuters.com"}
            or not path_parts
            or path_parts[0].casefold() in _NON_ENGLISH_PREFIXES
            or url in seen_urls
        ):
            continue

        news_node = node.find(f"{{{_NEWS_NS}}}news")
        if news_node is None:
            continue
        title = _xml_text(news_node, f"{{{_NEWS_NS}}}title")
        timestamp = _iso_timestamp_ms(
            _xml_text(news_node, f"{{{_NEWS_NS}}}publication_date")
        )
        if not title or timestamp is None:
            continue

        image_node = node.find(f"{{{_IMAGE_NS}}}image")
        cover = (
            _xml_text(image_node, f"{{{_IMAGE_NS}}}loc")
            if image_node is not None
            else ""
        )
        section = " / ".join(path_parts[:-1][:2])
        seen_urls.add(url)
        items.append(
            ListItem(
                id="/".join(path_parts),
                title=title,
                author="Reuters",
                desc=f"栏目：{section}" if section else None,
                cover=cover or None,
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


def _iso_timestamp_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None
