from __future__ import annotations

import re
from defusedxml import ElementTree as ET
from email.utils import parsedate_to_datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "lobsters"

SOURCE_LINK = "https://lobste.rs/"
TYPE_MAP = {"links": "Links", "active": "Active", "ai": "AI"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Lobsters",
    "description": "Programming and open source links from Lobsters",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "榜单分类", "type": TYPE_MAP}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "links")
    board_type = requested_type if requested_type in TYPE_MAP else "links"
    list_data = await _get_list(no_cache, board_type)
    return RouterData(
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool, board_type: str = "links") -> dict:
    if board_type == "active":
        return await _get_active_list(no_cache)
    if board_type == "ai":
        return await _get_ai_list(no_cache)
    result = await get(
        url="https://lobste.rs/rss",
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )

    root = ET.fromstring(result.data)
    data: list[ListItem] = []
    for item in root.findall("./channel/item"):
        title = _xml_text(item, "title")
        url = _xml_text(item, "link")
        if not title or not url:
            continue
        comments = _xml_text(item, "comments")
        data.append(
            ListItem(
                id=_story_id(_xml_text(item, "guid") or comments) or url,
                title=title,
                author=_xml_text(item, "author") or None,
                desc=", ".join(_categories(item)) or None,
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


async def _get_active_list(no_cache: bool) -> dict:
    result = await get(
        "https://lobste.rs/active.json",
        no_cache=no_cache,
        response_type="json",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
    )
    data = _build_active_items(result.data)
    if not data:
        raise ValueError("Lobsters active feed returned no valid stories")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _get_ai_list(no_cache: bool) -> dict:
    result = await get(
        "https://lobste.rs/t/ai.rss",
        no_cache=no_cache,
        response_type="text",
        headers={"Accept": "application/rss+xml, application/xml, text/xml", "Referer": SOURCE_LINK},
    )
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)}


def _build_active_items(rows: object) -> list[ListItem]:
    if not isinstance(rows, list):
        raise ValueError("Lobsters active response is not a list")
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("short_id") or "").strip().lower()
        title = str(row.get("title") or "").strip()
        comments_url = str(row.get("comments_url") or "").strip()
        if not (re.fullmatch(r"[a-z0-9]{6}", item_id) and title and comments_url.startswith(f"https://lobste.rs/s/{item_id}")):
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        score = row.get("score")
        comments = row.get("comment_count")
        tags = [str(tag).strip() for tag in row.get("tags") or [] if str(tag).strip()]
        description = []
        if isinstance(comments, int) and comments >= 0:
            description.append(f"评论：{comments}")
        if isinstance(score, int) and score >= 0:
            description.append(f"积分：{score}")
        if tags:
            description.append("标签：" + "、".join(tags[:6]))
        items.append(ListItem(
            id=item_id,
            title=title,
            author=str(row.get("submitter_user") or "").strip() or None,
            desc=" · ".join(description) or None,
            hot=comments if isinstance(comments, int) and comments >= 0 else score if isinstance(score, int) and score >= 0 else None,
            timestamp=get_time(row.get("created_at")),
            url=comments_url,
            mobileUrl=comments_url,
        ))
        if len(items) >= 25:
            break
    return items


def _xml_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _categories(item: ET.Element) -> list[str]:
    return [
        (node.text or "").strip()
        for node in item.findall("category")
        if (node.text or "").strip()
    ]


def _story_id(value: str) -> str | None:
    match = re.search(r"/s/([^/]+)", value)
    return match.group(1) if match else None


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
