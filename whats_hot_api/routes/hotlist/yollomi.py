from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
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
    "description": "Yollomi Gallery 公开 AI 图片与视频作品流",
    "params": {
        "type": {
            "name": "作品类型",
            "type": type_map,
        },
    },
    "link": "https://yollomi.com/gallery",
}

_BASE_URL = "https://yollomi.com"
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
    url = (
        f"{_BASE_URL}/gallery"
        if board_type == "all"
        else f"{_BASE_URL}/gallery?type={board_type}"
    )
    result = await get(
        url=url,
        no_cache=no_cache,
        cache_key=f"yollomi:gallery:{board_type}",
        response_type="text",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_gallery(result.data, board_type),
    }


def _parse_gallery(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, str) or not payload.strip() or board_type not in type_map:
        return []
    soup = BeautifulSoup(payload, "lxml")
    links = soup.select('a[href^="/creation/"]')
    if not links:
        return []

    expected_kind = {"images": "Image", "videos": "Video"}.get(board_type)
    items: list[ListItem] = []
    seen_tokens: set[str] = set()
    seen_media: set[str] = set()
    for link in links:
        href = _clean_text(link.get("href"))
        token = href.removeprefix("/creation/")
        identity = _decode_identity(token)
        prompt = _clean_text(
            link.select_one("p.line-clamp-3").get_text(" ", strip=True)
            if link.select_one("p.line-clamp-3") is not None
            else ""
        )
        model_node = link.select_one("span.inline-flex.min-w-0")
        model = _clean_text(model_node.get_text(" ", strip=True) if model_node else "")
        kinds = {
            _clean_text(node.get_text(" ", strip=True))
            for node in link.select("span")
        } & {"Image", "Video"}
        if (
            identity is None
            or not prompt
            or not model
            or len(kinds) != 1
            or (expected_kind is not None and kinds != {expected_kind})
            or token in seen_tokens
            or identity["media_url"] in seen_media
        ):
            return []

        kind = kinds.pop()
        if not _media_matches_kind(identity["media_url"], kind):
            return []
        seen_tokens.add(token)
        seen_media.add(identity["media_url"])
        url = f"{_BASE_URL}{href}"
        desc_prompt = _truncate(prompt, 500)
        items.append(
            ListItem(
                id=hashlib.sha256(token.encode()).hexdigest(),
                title=_truncate(prompt, 120),
                author=model,
                desc=f"类型：{'图片' if kind == 'Image' else '视频'} · 提示词：{desc_prompt}",
                cover=identity["media_url"] if kind == "Image" else None,
                timestamp=get_time(identity["created_time"]),
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _decode_identity(token: str) -> dict[str, str] | None:
    if not token or len(token) > 2048:
        return None
    try:
        padding = "=" * (-len(token) % 4)
        value = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {"mediaUrl", "createdTime"}:
        return None
    media_url = _clean_text(value.get("mediaUrl"))
    created_time = _clean_text(value.get("createdTime"))
    parsed = urlparse(media_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _MEDIA_HOST
        or parsed.username
        or parsed.query
        or parsed.fragment
        or not parsed.path
    ):
        return None
    try:
        timestamp = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None or get_time(created_time) is None:
        return None
    return {"media_url": media_url, "created_time": created_time}


def _media_matches_kind(media_url: str, kind: str) -> bool:
    path = urlparse(media_url).path.casefold()
    suffixes = _IMAGE_SUFFIXES if kind == "Image" else _VIDEO_SUFFIXES
    return path.endswith(suffixes)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
