from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics

ROUTE_NAME = "telegram-osint"

CHANNELS: dict[str, dict[str, str]] = {
    "intelslava": {"id": "intelslava", "label": "Intel Slava Z"},
    "legitimniy": {"id": "legitimniy", "label": "Legitimniy"},
    "wartranslated": {"id": "wartranslated", "label": "War Translated"},
    "mod-russia": {"id": "mod_russia", "label": "俄罗斯国防部"},
    "cig": {"id": "CIG_telegram", "label": "Conflict Intelligence Team"},
    "rvvoenkor": {"id": "RVvoenkor", "label": "Voenkor RV"},
    "readovkanews": {"id": "readovkanews", "label": "Readovka"},
    "deepstateua": {"id": "DeepStateUA", "label": "DeepState Ukraine"},
    "operativnozsu": {"id": "operativnoZSU", "label": "ZSU Operative"},
    "generalstaffzsu": {"id": "GeneralStaffZSU", "label": "乌克兰武装部队总参谋部"},
}

type_map: dict[str, str] = {key: value["label"] for key, value in CHANNELS.items()}

SOURCE_LINK = "https://t.me/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Telegram OSINT",
    "description": "Telegram 活跃公开冲突与地缘信息频道动态（保留原始发布者观点）",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "公开频道",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "intelslava")
    selected_type = requested_type if requested_type in CHANNELS else "intelslava"
    list_data = await _get_channel(selected_type, no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_channel(selected_type: str, no_cache: bool) -> dict:
    channel = CHANNELS[selected_type]
    channel_id = channel["id"]
    url = f"https://t.me/s/{channel_id}"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    soup = BeautifulSoup(result.data or "", "lxml")
    data: list[NewsFlashItem] = []
    for node in soup.select(".tgme_widget_message[data-post]"):
        post_id = str(node.get("data-post") or "")
        prefix, separator, message_id = post_id.partition("/")
        if not separator or prefix.lower() != channel_id.lower() or not message_id:
            continue

        text_node = node.select_one(".tgme_widget_message_text")
        content = text_node.get_text("\n", strip=True) if text_node else ""
        content = "\n".join(line.strip() for line in content.splitlines() if line.strip())
        if not content:
            continue

        bounded_content, status = _bounded_content(content)
        title = _title_from_content(content)
        time_node = node.select_one("time[datetime]")
        views_node = node.select_one(".tgme_widget_message_views")
        detail_url = f"https://t.me/{channel_id}/{message_id}"
        data.append(
            NewsFlashItem(
                id=post_id,
                title=title,
                content=bounded_content,
                summary=content[:300] if len(content) > 300 else None,
                contentStatus=status,
                source=channel["label"],
                tags=["Telegram", "OSINT"],
                metrics=metrics(
                    views=_parse_views(views_node.get_text(strip=True) if views_node else None),
                    channel=channel_id,
                    hasMedia=node.select_one(
                        ".tgme_widget_message_photo, .tgme_widget_message_video"
                    )
                    is not None,
                ),
                timestamp=get_time(time_node.get("datetime") if time_node else None),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data[:20],
    }


def _title_from_content(content: str, limit: int = 120) -> str:
    first_line = content.splitlines()[0].strip()
    if len(first_line) <= limit:
        return first_line
    return f"{first_line[:limit].rstrip()}…"


def _bounded_content(value: str, limit: int = 1200) -> tuple[str, str]:
    if len(value) <= limit:
        return value, "full"
    return f"{value[:limit].rstrip()}…", "truncated"


def _parse_views(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.strip().upper().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KM]?)", normalized)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000}[match.group(2)]
    return int(number * multiplier)
