from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "spotify"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Spotify",
    "description": "Spotify 全球每日播放量最高的 50 首歌曲",
    "link": "https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF",
}

_PLAYLIST_ID = "37i9dQZEVXbMDoHDwVN2tF"
_EMBED_URL = f"https://open.spotify.com/embed/playlist/{_PLAYLIST_ID}"
_TRACK_ID_RE = re.compile(r"[A-Za-z0-9]{22}")
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="全球 Top 50",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_EMBED_URL,
        no_cache=no_cache,
        cache_key="spotify:global-top-50",
        response_type="text",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_playlist(result.data),
    }


def _parse_playlist(payload: object) -> list[ListItem]:
    if not isinstance(payload, str) or not payload.strip():
        return []
    soup = BeautifulSoup(payload, "lxml")
    script = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if script is None or not script.string:
        return []
    try:
        root = json.loads(script.string)
    except (TypeError, json.JSONDecodeError):
        return []

    entity = _nested(root, "props", "pageProps", "state", "data", "entity")
    if not _is_global_chart(entity):
        return []
    rows = entity.get("trackList")
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        item = _track_item(row)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _is_global_chart(entity: object) -> bool:
    if not isinstance(entity, dict):
        return False
    attributes = entity.get("attributes")
    if not isinstance(attributes, list):
        return False
    attribute_map = {
        _clean_text(item.get("key")): _clean_text(item.get("value"))
        for item in attributes
        if isinstance(item, dict)
    }
    return (
        entity.get("id") == _PLAYLIST_ID
        and entity.get("uri") == f"spotify:playlist:{_PLAYLIST_ID}"
        and _clean_text(entity.get("name")) == "Top 50 - Global"
        and _clean_text(entity.get("subtitle")) == "Spotify"
        and entity.get("format") == "chart"
        and attribute_map.get("rank_type") == "plays"
        and attribute_map.get("chart_entity_type") == "track"
        and bool(attribute_map.get("last_updated"))
    )


def _track_item(row: object) -> ListItem | None:
    if not isinstance(row, dict) or row.get("entityType") != "track":
        return None
    uri = _clean_text(row.get("uri"))
    track_id = uri.removeprefix("spotify:track:")
    title = _clean_text(row.get("title"))
    artist = _clean_text(row.get("subtitle"))
    if (
        uri != f"spotify:track:{track_id}"
        or not _TRACK_ID_RE.fullmatch(track_id)
        or not title
        or not artist
    ):
        return None

    desc_parts: list[str] = []
    duration = _duration_label(row.get("duration"))
    if duration:
        desc_parts.append(f"时长：{duration}")
    if row.get("isExplicit") is True:
        desc_parts.append("Explicit")
    url = f"https://open.spotify.com/track/{track_id}"
    return ListItem(
        id=track_id,
        title=title,
        author=artist,
        desc=" · ".join(desc_parts) or None,
        url=url,
        mobileUrl=url,
    )


def _duration_label(value: object) -> str:
    try:
        seconds = int(value) // 1000
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def _nested(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
