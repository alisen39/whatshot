from __future__ import annotations

from urllib.parse import urlparse

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "yollomi"

type_map: dict[str, str] = {
    "all": "综合公开作品",
    "images": "图片作品",
    "videos": "视频作品",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Yollomi",
    "description": "Yollomi Explore 公开 AI 图片与视频作品流",
    "params": {
        "type": {
            "name": "作品类型",
            "type": type_map,
        },
    },
    "link": "https://yollomi.com/explore",
}

_API_URL = "https://yollomi.com/api/explore"
_MEDIA_HOST = "pub-f11e69dd929f418fb2fd4811764d8285.r2.dev"
_IMAGE_SUFFIXES = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")
_VIDEO_SUFFIXES = (".mp4", ".webm")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "all")
    selected = requested if requested in type_map else "all"
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
    result = await get(
        url=_API_URL,
        params={"type": board_type, "limit": "50", "offset": "0"},
        no_cache=no_cache,
        cache_key=f"yollomi:explore:{board_type}",
        response_type="json",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_items(result.data, board_type),
    }


def _parse_items(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, dict) or board_type not in type_map:
        return []
    rows = payload.get("items")
    if not isinstance(rows, list):
        return []

    expected_kind = {"images": "image", "videos": "video"}.get(board_type)
    items: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = _text(row.get("id"))
        title = _text(row.get("title"))
        kind = _text(row.get("type")).casefold()
        preview = row.get("previewData")
        if (
            not item_id
            or item_id in seen_ids
            or not title
            or kind not in {"image", "video"}
            or (expected_kind is not None and kind != expected_kind)
            or not isinstance(preview, dict)
        ):
            continue

        media_url = _media_url(preview.get("media_url"), kind)
        created_time = _text(preview.get("created_time"))
        timestamp = get_time(created_time)
        if media_url is None or timestamp is None:
            continue

        cover = _media_url(row.get("image"), "image") if kind == "image" else None
        author = _text(row.get("author")) or _text(preview.get("username"))
        model = _text(preview.get("model"))
        details = [f"类型：{'图片' if kind == 'image' else '视频'}"]
        if model:
            details.append(f"模型：{model}")
        details.append(f"提示词：{_truncate(title, 500)}")
        seen_ids.add(item_id)
        items.append(
            ListItem(
                id=item_id,
                title=_truncate(title, 120),
                author=author or None,
                desc=" · ".join(details),
                hot=_number(row.get("likes")),
                cover=cover,
                timestamp=timestamp,
                url=media_url,
                mobileUrl=media_url,
            )
        )
    return items


def _media_url(value: object, kind: str) -> str | None:
    url = _text(value)
    parsed = urlparse(url)
    suffixes = _IMAGE_SUFFIXES if kind == "image" else _VIDEO_SUFFIXES
    if (
        parsed.scheme != "https"
        or parsed.hostname != _MEDIA_HOST
        or parsed.username
        or not parsed.path.casefold().endswith(suffixes)
    ):
        return None
    return url


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
