from __future__ import annotations

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

_READER_BASE = "https://r.jina.ai/http://uiverse.io/elements"
_ITEM_RE = re.compile(
    r"^\[Get code\]\(https?://(?:www\.)?uiverse\.io/"
    r"(?P<username>[A-Za-z0-9_.-]+)/(?P<slug>[A-Za-z0-9-]+)\)"
    r"(?P<body>.*?)(?=^\[Get code\]\(|\Z)",
    re.MULTILINE | re.DOTALL,
)
_METRICS_RE = re.compile(
    r"^(?P<views>\d+(?:\.\d+)?[KMB]?) views"
    r"(?:\s+(?P<favorites>\d+(?:\.\d+)?[KMB]?))?\s*$",
    re.MULTILINE,
)
_MAX_ITEMS = 50


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
        url=f"{_READER_BASE}?orderBy={board_type}",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"uiverse:elements:{board_type}:page-1",
        headers={
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_elements(result.data, board_type),
    }


def _parse_elements(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, str) or board_type not in type_map:
        return []
    label = {
        "favorites": "Favorites",
        "views": "Views",
        "recent": "Recent",
    }[board_type]
    if not _valid_source(payload, board_type, label):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    previous_metric: int | None = None
    for match in _ITEM_RE.finditer(payload):
        item = _element_item(match, board_type)
        if item is None or item.id in seen_ids:
            continue
        metric = item.hot
        if (
            board_type != "recent"
            and metric is not None
            and previous_metric is not None
            and metric > previous_metric
        ):
            return []
        seen_ids.add(item.id)
        if metric is not None:
            previous_metric = metric
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _valid_source(payload: str, board_type: str, label: str) -> bool:
    source_pattern = re.compile(
        rf"^URL Source: https?://(?:www\.)?uiverse\.io/elements\?orderBy={board_type}\s*$",
        re.MULTILINE,
    )
    return source_pattern.search(payload) is not None and f"Sort: {label}" in payload


def _element_item(match: re.Match[str], board_type: str) -> ListItem | None:
    username = match.group("username")
    slug = match.group("slug")
    body = match.group("body")
    canonical_url = f"https://uiverse.io/{username}/{slug}"
    escaped_url = re.escape(f"http://uiverse.io/{username}/{slug}")
    escaped_https_url = re.escape(canonical_url)
    if re.search(rf"^\[Link to post\]\((?:{escaped_url}|{escaped_https_url})\)\s*$", body, re.MULTILINE) is None:
        return None
    escaped_username = re.escape(username)
    if re.search(
        rf"^\[{escaped_username}\]\(https?://(?:www\.)?uiverse\.io/profile/{escaped_username}\)\s*$",
        body,
        re.MULTILINE,
    ) is None:
        return None
    metrics = _METRICS_RE.search(body)
    views = _compact_count(metrics.group("views")) if metrics is not None else None
    favorites = (
        _compact_count(metrics.group("favorites") or "0") if metrics is not None else None
    )
    if metrics is not None and (views is None or favorites is None):
        return None

    hot = favorites if board_type == "favorites" else views
    title = " ".join(slug.split("-")).capitalize()
    desc = f"{views} 次浏览 · {favorites} 次收藏" if views is not None else None
    return ListItem(
        id=f"{username}/{slug}",
        title=title,
        author=username,
        desc=desc,
        hot=hot,
        url=canonical_url,
        mobileUrl=canonical_url,
    )


def _compact_count(value: str) -> int | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB]?)", value.strip(), re.IGNORECASE)
    if match is None:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        match.group(2).upper()
    ]
    return round(float(match.group(1)) * multiplier)
