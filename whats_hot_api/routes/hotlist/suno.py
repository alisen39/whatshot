from __future__ import annotations

import re
from urllib.parse import urlparse

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "suno"

type_map: dict[str, str] = {
    "trending": "主题趋势",
    "staff-picks": "编辑精选",
    "best-model": "最佳模型作品",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Suno",
    "description": "Suno Explore 官方趋势与编辑精选 AI 音乐",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
    "link": "https://suno.com/explore",
}

_API_URL = "https://studio-api-prod.suno.com/api/unified/homepage/explore"
_PLAYLIST_ID_RE = re.compile(
    r"generic_playlist:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_CLIP_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_MAX_ITEMS = 10


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "trending")
    selected_type = type_param if type_param in type_map else "trending"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **{
            **ROUTE_META,
            "link": list_data["link"] or ROUTE_META["link"],
        },
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    result = await post(
        url=_API_URL,
        body={"cursor": None, "page_size": 20},
        no_cache=no_cache,
        cache_key="suno:explore",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/explore",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    parsed = _parse_board(result.data, board_type)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "link": parsed["link"],
        "data": parsed["data"],
    }


def _parse_board(payload: object, board_type: str) -> dict:
    if not isinstance(payload, dict) or board_type not in type_map:
        return {"link": "", "data": []}
    feeds = payload.get("feeds")
    if not isinstance(feeds, list):
        return {"link": "", "data": []}

    matches = [feed for feed in feeds if _matches_board(feed, board_type)]
    if len(matches) != 1:
        return {"link": "", "data": []}
    feed = matches[0]
    playlist = _validated_playlist(feed)
    if playlist is None:
        return {"link": "", "data": []}
    playlist_id = playlist

    rows = feed.get("items")
    if not isinstance(rows, list):
        return {"link": "", "data": []}
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        item = _clip_item(row)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    if not data:
        return {"link": "", "data": []}
    return {
        "link": f"https://suno.com/playlist/{playlist_id}",
        "data": data,
    }


def _matches_board(feed: object, board_type: str) -> bool:
    if not isinstance(feed, dict):
        return False
    title = _clean_text(feed.get("feed_title"))
    if board_type == "trending":
        return title.startswith("Trending:")
    if board_type == "staff-picks":
        return title == "Staff Picks"
    return bool(re.fullmatch(r"Best of v\d+(?:\.\d+)*", title))


def _validated_playlist(feed: dict) -> str | None:
    if feed.get("feed_container_type") != "playlist":
        return None
    feed_id = _clean_text(feed.get("feed_id"))
    match = _PLAYLIST_ID_RE.fullmatch(feed_id)
    if match is None:
        return None
    playlist_id = match.group(1).lower()
    if _clean_text(feed.get("feed_container_id")).lower() != playlist_id:
        return None
    link = _clean_text(feed.get("feed_direct_link"))
    if link != f"/playlist/{playlist_id}":
        return None
    return playlist_id


def _clip_item(row: object) -> ListItem | None:
    if not isinstance(row, dict) or row.get("content_type") != "clip":
        return None
    clip = row.get("content_item")
    if not isinstance(clip, dict):
        return None
    clip_id = _clean_text(clip.get("id")).lower()
    title = _clean_text(clip.get("title"))
    if (
        not _CLIP_ID_RE.fullmatch(clip_id)
        or _clean_text(row.get("content_id")).lower() != clip_id
        or clip.get("entity_type") != "song_schema"
        or clip.get("is_public") is not True
        or clip.get("status") != "complete"
        or not title
    ):
        return None

    desc_parts: list[str] = []
    model_name = _clean_text(clip.get("model_name"))
    if model_name:
        desc_parts.append(f"模型：{model_name}")
    metadata = clip.get("metadata")
    if isinstance(metadata, dict):
        duration = _duration_label(metadata.get("duration"))
        if duration:
            desc_parts.append(f"时长：{duration}")
        tags = _clean_text(metadata.get("tags"))
        if tags:
            desc_parts.append(tags[:240])
    if clip.get("upvote_count") is not None:
        desc_parts.append(f"点赞：{clip['upvote_count']}")

    url = f"https://suno.com/song/{clip_id}"
    return ListItem(
        id=clip_id,
        title=title,
        author=_clean_text(clip.get("display_name")) or None,
        desc=" · ".join(desc_parts) or None,
        hot=clip.get("play_count"),
        cover=_https_url(clip.get("image_url")),
        timestamp=get_time(clip.get("created_at")),
        url=url,
        mobileUrl=url,
    )


def _duration_label(value: object) -> str:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def _https_url(value: object) -> str | None:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return url


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
