from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "pixiv"

type_map: dict[str, str] = {
    "daily": "每日综合",
    "weekly": "每周综合",
    "monthly": "每月综合",
    "rookie": "新人榜",
    "original": "原创榜",
    "male": "男性向",
    "female": "女性向",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Pixiv",
    "description": "Pixiv 插画作品排行榜",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.pixiv.net/ranking.php",
}

_RANKING_URL = "https://www.pixiv.net/ranking.php"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "daily")
    selected_type = type_param if type_param in type_map else "daily"
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
        url=_RANKING_URL,
        no_cache=no_cache,
        response_type="json",
        params={"mode": board_type, "p": "1", "format": "json"},
        cache_key=f"{_RANKING_URL}?mode={board_type}&p=1&format=json",
        headers={
            "Accept": "application/json",
            "Referer": "https://www.pixiv.net/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    data = [_ranking_item(row) for row in (result.data or {}).get("contents", [])]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _ranking_item(row: dict) -> ListItem | None:
    illust_id = str(row.get("illust_id") or "").strip()
    title = str(row.get("title") or "").strip()
    if not illust_id or not title:
        return None
    url = f"https://www.pixiv.net/artworks/{illust_id}"
    tags = [str(tag).strip() for tag in row.get("tags", []) if str(tag).strip()]
    desc_parts = []
    if row.get("illust_page_count") is not None:
        desc_parts.append(f"页数：{row['illust_page_count']}")
    if tags:
        desc_parts.append("标签：" + "、".join(tags[:6]))
    return ListItem(
        id=illust_id,
        title=title,
        author=str(row.get("user_name") or "").strip() or None,
        desc=" · ".join(desc_parts) or None,
        hot=row.get("illust_bookmark_count"),
        cover=str(row.get("url") or "").strip() or None,
        timestamp=_pixiv_time(row.get("date")),
        url=url,
        mobileUrl=url,
    )


def _pixiv_time(value: object) -> int | None:
    text = str(value or "").strip()
    match = re.fullmatch(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{2}))?", text
    )
    if not match:
        return get_time(text)
    year, month, day, hour, minute = match.groups()
    return get_time(
        f"{year}-{int(month):02d}-{int(day):02d} "
        f"{int(hour or 0):02d}:{int(minute or 0):02d}:00"
    )
