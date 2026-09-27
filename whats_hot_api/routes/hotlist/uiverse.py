from __future__ import annotations

import math
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "uiverse"

type_map: dict[str, str] = {
    "favorites": "收藏最多",
    "views": "浏览最多",
    "recent": "最新发布",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Uiverse",
    "description": "Uiverse 开源 UI 元素收藏、浏览与最新发布榜",
    "params": {
        "type": {
            "name": "元素榜",
            "type": type_map,
        },
    },
    "link": "https://uiverse.io/elements",
}

# Remix single-fetch data endpoint of the elements page; it returns the same
# server-loader JSON the HTML embeds, without requiring a browser runtime.
_ELEMENTS_URL = "https://uiverse.io/elements"
_ELEMENTS_DATA_PARAM = "routes/$category"
_MAX_ITEMS = 50
_MIN_USABLE_RATIO = 0.8
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "favorites")
    selected_type = type_param if type_param in type_map else "favorites"
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
        url=_ELEMENTS_URL,
        params={"orderBy": board_type, "_data": _ELEMENTS_DATA_PARAM},
        no_cache=no_cache,
        response_type="json",
        cache_key=f"uiverse:elements:{board_type}:page-1",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_elements(result.data, board_type),
    }


def _parse_elements(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, dict) or board_type not in type_map:
        raise RuntimeError("uiverse elements response is not a JSON object")
    posts = payload.get("posts")
    if not isinstance(posts, list) or not posts:
        raise RuntimeError("uiverse elements response has no posts")

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for post in posts:
        item = _element_item(post)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    minimum_usable = math.ceil(min(len(posts), _MAX_ITEMS) * _MIN_USABLE_RATIO)
    if len(data) < minimum_usable:
        raise RuntimeError("uiverse elements response has too few usable posts")
    return data


def _element_item(post: object) -> ListItem | None:
    if not isinstance(post, dict):
        return None
    friendly_id = post.get("friendlyId")
    user = post.get("user")
    username = user.get("username") if isinstance(user, dict) else None
    if (
        not isinstance(friendly_id, str)
        or _PATH_SEGMENT_RE.fullmatch(friendly_id) is None
        or not isinstance(username, str)
        or _PATH_SEGMENT_RE.fullmatch(username) is None
    ):
        return None
    canonical_url = f"https://uiverse.io/{username}/{friendly_id}"
    return ListItem(
        id=f"{username}/{friendly_id}",
        title=" ".join(str(friendly_id).split("-")).capitalize(),
        author=username,
        url=canonical_url,
        mobileUrl=canonical_url,
    )
