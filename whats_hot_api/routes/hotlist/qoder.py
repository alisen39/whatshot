from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qoder"

SOURCE_LINK = "https://qoder.com/blog"

type_map: dict[str, str] = {
    "blog": "官方博客",
    "changelog": "更新日志",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Qoder",
    "description": "Qoder 官方产品、技术、案例文章与版本更新",
    "params": {
        "type": {
            "name": "内容分类",
            "type": type_map,
        },
    },
    "link": SOURCE_LINK,
}

_BOARD_URLS = {
    "blog": "https://qoder.com/blog",
    "changelog": "https://qoder.com/en/changelog",
}
_MAX_ITEMS = 50
_NEXT_FRAME_PREFIX = "self.__next_f.push("
_BLOG_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PRODUCT_NAMES = {
    "cli": "Qoder CLI",
    "cloudagents": "Cloud Agents",
    "ide": "Qoder IDE",
    "jetbrains": "JetBrains Plugin",
    "plugin": "JetBrains Plugin",
    "qoderwake": "QoderWake",
    "qoderwork": "QoderWork",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "blog")
    selected = requested if requested in type_map else "blog"
    list_data = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    url = _BOARD_URLS[board_type]
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://qoder.com/",
        },
        cache_key=f"qoder:{board_type}:latest:{_MAX_ITEMS}",
    )
    parser = _parse_blog if board_type == "blog" else _parse_changelog
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": parser(result.data),
    }


def _parse_blog(html: str) -> list[ListItem]:
    records = _next_records(html)
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in records:
        slug = _text(row.get("url"))
        title = _text(row.get("title"))
        published_at = _text(row.get("published_at"))
        if (
            not _BLOG_SLUG_RE.fullmatch(slug)
            or not title
            or not published_at
            or slug in seen
        ):
            continue
        timestamp = _iso_ms(published_at)
        if timestamp is None:
            continue
        seen.add(slug)
        url = f"https://qoder.com/blog/{quote(slug)}"
        items.append(
            ListItem(
                id=slug,
                title=title,
                author=_text(row.get("category")) or "Qoder",
                desc=_summary(row.get("desc")),
                cover=_http_url(row.get("img")),
                timestamp=timestamp,
                url=url,
                mobileUrl=url,
            )
        )
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items[:_MAX_ITEMS]


def _parse_changelog(html: str) -> list[ListItem]:
    records = _next_records(html)
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in records:
        item_id = _text(row.get("id"))
        title = _text(row.get("title"))
        version = _text(row.get("tag_name"))
        product_key = _text(row.get("type")).lower()
        published_at = _text(row.get("published_at"))
        if (
            not item_id.isdigit()
            or not title
            or not version
            or not product_key
            or not published_at
            or item_id in seen
        ):
            continue
        timestamp = _iso_ms(published_at)
        if timestamp is None:
            continue
        seen.add(item_id)
        product = _PRODUCT_NAMES.get(product_key, product_key)
        url = f"https://qoder.com/en/changelog?version={quote(version)}"
        body = _summary(row.get("body"))
        desc = f"版本：{version}"
        if body:
            desc = f"{desc} · {body}"
        items.append(
            ListItem(
                id=item_id,
                title=title,
                author=product,
                desc=desc,
                timestamp=timestamp,
                url=url,
                mobileUrl=url,
            )
        )
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items[:_MAX_ITEMS]


def _next_records(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text.startswith(_NEXT_FRAME_PREFIX) or not text.endswith(")"):
            continue
        try:
            frame = json.loads(text[len(_NEXT_FRAME_PREFIX) : -1])
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            not isinstance(frame, list)
            or len(frame) < 2
            or not isinstance(frame[1], str)
        ):
            continue
        for line in frame[1].splitlines():
            payload = line.partition(":")[2]
            if not payload.startswith(("{", "[")):
                continue
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            _collect_records(value, records)
    return records


def _collect_records(value: object, records: list[dict]) -> None:
    if isinstance(value, dict):
        if value.get("published_at") and value.get("title"):
            records.append(value)
        for child in value.values():
            _collect_records(child, records)
    elif isinstance(value, list):
        for child in value:
            _collect_records(child, records)


def _summary(value: object) -> str | None:
    text = BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)
    return text[:240] or None


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _http_url(value: object) -> str | None:
    url = _text(value)
    return url if url.startswith(("https://", "http://")) else None


def _iso_ms(value: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None
