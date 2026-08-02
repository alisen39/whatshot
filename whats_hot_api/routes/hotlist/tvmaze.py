from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "tvmaze"

type_map: dict[str, str] = {
    "us": "美国电视今日播出",
    "web": "全球流媒体今日播出",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "TVmaze",
    "description": "TVmaze 官方当日电视与流媒体节目播出表",
    "params": {
        "type": {
            "name": "播出表",
            "type": type_map,
        },
    },
    "link": "https://www.tvmaze.com/schedule",
}

_API_BASE = "https://api.tvmaze.com"
_EPISODE_PATH_RE = re.compile(r"/episodes/(\d+)(?:/[^/?#]+)?/?")
_MAX_ITEMS = 200


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "us")
    selected_type = type_param if type_param in type_map else "us"
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
    url = f"{_API_BASE}/schedule/web" if board_type == "web" else f"{_API_BASE}/schedule"
    result = await get(
        url=url,
        no_cache=no_cache,
        cache_key=f"tvmaze:schedule:{board_type}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_schedule(result.data, board_type),
    }


def _parse_schedule(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, list) or board_type not in type_map:
        return []
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    previous_time = 0
    for row in payload:
        item = _episode_item(row, board_type)
        if item is None or item.id in seen_ids:
            continue
        if item.timestamp is not None and item.timestamp < previous_time:
            return []
        seen_ids.add(item.id)
        previous_time = item.timestamp or previous_time
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _episode_item(value: object, board_type: str) -> ListItem | None:
    if not isinstance(value, dict):
        return None
    episode_id = _clean_text(value.get("id"))
    episode_name = _clean_text(value.get("name"))
    episode_url = _validated_episode_url(value.get("url"), episode_id)
    links = value.get("_links")
    if (
        not episode_id.isdigit()
        or int(episode_id) <= 0
        or not episode_name
        or episode_url is None
        or not isinstance(links, dict)
        or _link_field(links.get("self"), "href") != f"{_API_BASE}/episodes/{episode_id}"
    ):
        return None

    embedded = value.get("_embedded")
    show = value.get("show") if board_type == "us" else (
        embedded.get("show") if isinstance(embedded, dict) else None
    )
    if not isinstance(show, dict):
        return None
    show_id = _clean_text(show.get("id"))
    show_name = _clean_text(show.get("name"))
    show_link = links.get("show")
    if (
        not show_id.isdigit()
        or not show_name
        or not isinstance(show_link, dict)
        or _link_field(show_link, "href") != f"{_API_BASE}/shows/{show_id}"
        or _link_field(show_link, "name") != show_name
    ):
        return None

    airstamp = get_time(value.get("airstamp"))
    if airstamp is None or airstamp <= 0:
        return None
    channel = show.get("webChannel") if board_type == "web" else show.get("network")
    channel_name = _clean_text(channel.get("name")) if isinstance(channel, dict) else ""
    desc_parts: list[str] = []
    episode_label = _episode_label(value)
    if episode_label:
        desc_parts.append(episode_label)
    if channel_name:
        desc_parts.append(channel_name)
    runtime = value.get("runtime")
    if isinstance(runtime, (int, float)) and runtime > 0:
        desc_parts.append(f"{int(runtime)} 分钟")
    summary = _plain_text(value.get("summary"))
    if summary:
        desc_parts.append(summary[:360])

    title = show_name if episode_name == show_name else f"{show_name}：{episode_name}"
    return ListItem(
        id=episode_id,
        title=title,
        author=channel_name or None,
        desc=" · ".join(desc_parts) or None,
        cover=_cover_url(value, show),
        timestamp=airstamp,
        url=episode_url,
        mobileUrl=episode_url,
    )


def _validated_episode_url(value: object, episode_id: str) -> str | None:
    url = _clean_text(value)
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc != "www.tvmaze.com" or parsed.username:
        return None
    match = _EPISODE_PATH_RE.fullmatch(parsed.path)
    if match is None or match.group(1) != episode_id or parsed.query or parsed.fragment:
        return None
    return url


def _episode_label(value: dict) -> str:
    season = value.get("season")
    number = value.get("number")
    if isinstance(season, int) and season >= 0 and isinstance(number, int) and number >= 0:
        return f"S{season:02d}E{number:02d}"
    return ""


def _cover_url(episode: dict, show: dict) -> str | None:
    for source in (episode.get("image"), show.get("image")):
        if not isinstance(source, dict):
            continue
        for key in ("original", "medium"):
            url = _https_url(source.get(key))
            if url:
                return url
    return None


def _https_url(value: object) -> str | None:
    url = _clean_text(value)
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return url


def _plain_text(value: object) -> str:
    return BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)


def _link_field(value: object, key: str) -> str:
    return _clean_text(value.get(key)) if isinstance(value, dict) else ""


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
