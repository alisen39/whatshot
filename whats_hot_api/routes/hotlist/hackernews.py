from __future__ import annotations

import asyncio
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hackernews"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
_MAX_ITEMS = 30

TYPE_MAP = {
    "top": "Popular",
    "best": "Best",
    "show": "Show HN",
    "ask": "Ask HN",
    "jobs": "Jobs",
    "new": "New",
}
_ENDPOINTS = {
    "top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "best": "https://hacker-news.firebaseio.com/v0/beststories.json",
    "show": "https://hacker-news.firebaseio.com/v0/showstories.json",
    "ask": "https://hacker-news.firebaseio.com/v0/askstories.json",
    "jobs": "https://hacker-news.firebaseio.com/v0/jobstories.json",
    "new": "https://hacker-news.firebaseio.com/v0/newstories.json",
}
_LINKS = {
    "top": "https://news.ycombinator.com/",
    "best": "https://news.ycombinator.com/best",
    "show": "https://news.ycombinator.com/show",
    "ask": "https://news.ycombinator.com/ask",
    "jobs": "https://news.ycombinator.com/jobs",
    "new": "https://news.ycombinator.com/newest",
}

ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "Hacker News",
    "description": "Hacker News stories, launches, questions, jobs and newest posts.",
    "link": _LINKS["top"],
    "params": {"type": {"name": "榜单分类", "type": TYPE_MAP}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", "top")
    selected_type = board_type if board_type in TYPE_MAP else "top"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": _LINKS[selected_type]},
        type=TYPE_MAP[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict[str, Any]:
    ids_result = await get(
        _ENDPOINTS[board_type],
        no_cache=no_cache,
        response_type="json",
        headers={"Accept": "application/json"},
    )
    ids = _valid_ids(ids_result.data)
    results = await asyncio.gather(
        *(
            get(
                _ITEM_URL.format(item_id=item_id),
                no_cache=no_cache,
                response_type="json",
                headers={"Accept": "application/json"},
            )
            for item_id in ids
        )
    )
    data = [
        item
        for item in (_item_from_row(result.data, board_type) for result in results)
        if item is not None
    ]
    return {
        "from_cache": ids_result.from_cache and all(result.from_cache for result in results),
        "update_time": ids_result.update_time,
        "data": data,
    }


def _valid_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        raise ValueError("Hacker News list response is not a list")
    ids: list[int] = []
    for item_id in value:
        if isinstance(item_id, int) and item_id > 0 and item_id not in ids:
            ids.append(item_id)
        if len(ids) >= _MAX_ITEMS:
            break
    if not ids:
        raise ValueError("Hacker News list response is empty")
    return ids


def _item_from_row(row: Any, board_type: str) -> ListItem | None:
    expected_type = "job" if board_type == "jobs" else "story"
    if not isinstance(row, dict) or row.get("type") != expected_type:
        return None
    if row.get("dead") or row.get("deleted"):
        return None
    item_id = row.get("id")
    title = str(row.get("title") or "").strip()
    if not isinstance(item_id, int) or item_id <= 0 or not title:
        return None
    discussion_url = f"https://news.ycombinator.com/item?id={item_id}"
    url = str(row.get("url") or discussion_url).strip()
    if not url.startswith(("https://", "http://")):
        url = discussion_url
    comments = row.get("descendants")
    return ListItem(
        id=str(item_id),
        title=title,
        author=str(row.get("by") or "").strip() or None,
        desc=(f"评论：{comments}" if isinstance(comments, int) and comments >= 0 else None),
        hot=row.get("score") if isinstance(row.get("score"), int) else None,
        timestamp=get_time(row.get("time")),
        url=url,
        mobileUrl=url,
    )
