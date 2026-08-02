from __future__ import annotations

import re
from urllib.parse import urljoin

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bluesky"
_API_URL = "https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics"
_POPULAR_FEEDS_URL = "https://public.api.bsky.app/xrpc/app.bsky.unspecced.getPopularFeedGenerators"
_FEED_URI_RE = re.compile(r"^at://(did:[a-z0-9:%._-]+)/app\.bsky\.feed\.generator/([a-z0-9._~-]+)$", re.IGNORECASE)

type_map: dict[str, str] = {"trending": "热门话题", "popular-feeds": "热门信息流"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Bluesky",
    "description": "Bluesky 当前热门话题",
    "link": "https://bsky.app/",
    "params": {"type": {"name": "榜单分类", "type": type_map}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected_type = request.query_params.get("type", "trending")
    if selected_type not in type_map:
        selected_type = "trending"
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
    if board_type == "popular-feeds":
        result = await get(url=_POPULAR_FEEDS_URL, params={"limit": "50"}, no_cache=no_cache, response_type="json", headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"})
        data = [item for item in (_feed_item(row) for row in (result.data or {}).get("feeds", [])) if item is not None]
    else:
        result = await get(url=_API_URL, no_cache=no_cache, response_type="json", headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"})
        data = []
        for row in (result.data or {}).get("topics", []):
            topic = str(row.get("topic") or "").strip()
            link = str(row.get("link") or "").strip()
            if not topic or not link:
                continue
            url = urljoin("https://bsky.app/", link)
            data.append(ListItem(id=link, title=topic, url=url, mobileUrl=url))
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


def _feed_item(row: object) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    uri = str(row.get("uri") or "").strip()
    name = str(row.get("displayName") or "").strip()
    match = _FEED_URI_RE.fullmatch(uri)
    if not match or not name:
        return None
    did, rkey = match.groups()
    creator = row.get("creator") if isinstance(row.get("creator"), dict) else {}
    handle = str(creator.get("handle") or "").strip()
    desc_parts = [str(row.get("description") or "").strip()]
    likes = row.get("likeCount")
    if isinstance(likes, int) and likes >= 0:
        desc_parts.append(f"点赞：{likes:,}")
    url = f"https://bsky.app/profile/{did}/feed/{rkey}"
    return ListItem(id=uri, title=name, author=handle or None, desc=" · ".join(part for part in desc_parts if part) or None, hot=likes if isinstance(likes, int) and likes >= 0 else None, cover=str(row.get("avatar") or "").strip() or None, url=url, mobileUrl=url)
