from __future__ import annotations

from html import unescape

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "producthunt"

type_map: dict[str, str] = {
    "today": "今日发布",
    "latest": "最新发布",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Product Hunt",
    "description": "Product Hunt 新产品发布",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.producthunt.com/",
}

_FEED_URL = "https://www.producthunt.com/feed"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "today")
    selected_type = type_param if type_param in type_map else "today"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    result = await get(
        url=_FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/atom+xml, application/xml, text/xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = _parse_feed(result.data or "")
    if board_type == "today" and rows:
        latest_date = max(row["published"][:10] for row in rows)
        rows = [row for row in rows if row["published"].startswith(latest_date)]
    data = [_feed_item(row) for row in rows]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _parse_feed(xml: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(xml, "xml")
    rows = []
    for entry in soup.find_all("entry"):
        link = entry.find("link", attrs={"rel": "alternate"}) or entry.find("link")
        content = entry.find("content")
        rows.append(
            {
                "id": _tag_text(entry, "id"),
                "title": _tag_text(entry, "title"),
                "author": _tag_text(entry.find("author"), "name"),
                "published": _tag_text(entry, "published"),
                "url": str(link.get("href") or "").strip() if link else "",
                "desc": _content_text(content.decode_contents() if content else ""),
            }
        )
    return rows


def _feed_item(row: dict[str, str]) -> ListItem | None:
    title = row["title"].strip()
    url = row["url"].strip()
    if not title or not url:
        return None
    item_id = row["id"].rsplit("/", 1)[-1].rsplit(":", 1)[-1] or url
    return ListItem(
        id=item_id,
        title=title,
        author=row["author"] or None,
        desc=row["desc"] or None,
        timestamp=get_time(row["published"]),
        url=url,
        mobileUrl=url,
    )


def _tag_text(parent, name: str) -> str:
    if parent is None:
        return ""
    tag = parent.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _content_text(value: str) -> str:
    text = BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)
    for suffix in ("Discussion | Link", "Discussion", "| Link"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text[:240]
