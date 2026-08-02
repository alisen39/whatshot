from __future__ import annotations

import math
from datetime import datetime, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "flathub"

type_map: dict[str, str] = {
    "trending": "两周趋势榜",
    "popular": "月度热门榜",
    "recently-added": "新上架",
    "recently-updated": "最近更新",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Flathub",
    "description": "Flathub Linux Flatpak 应用榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://flathub.org/apps",
}

_API_BASE = "https://flathub.org/api/v2/collection"
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "trending")
    selected_type = type_param if type_param in type_map else "trending"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **{
            **ROUTE_META,
            "link": f"https://flathub.org/apps/collection/{selected_type}",
        },
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    result = await get(
        url=f"{_API_BASE}/{board_type}",
        params={
            "page": "1",
            "per_page": str(_MAX_ITEMS),
            "locale": "en",
        },
        no_cache=no_cache,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = (result.data or {}).get("hits", []) if isinstance(result.data, dict) else []
    data = [
        item
        for rank, row in enumerate(rows[:_MAX_ITEMS], start=1)
        if (item := _app_item(row, rank, board_type)) is not None
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _app_item(row: object, rank: int, board_type: str) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    app_id = str(row.get("app_id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not app_id or not name or "." not in app_id:
        return None

    summary = _text(row.get("summary"))
    developer = _text(row.get("developer_name"))
    category = _category_text(row.get("main_categories"))
    license_name = _text(row.get("project_license"))
    installs = _integer(row.get("installs_last_month"))
    trending = _number(row.get("trending"))
    event_timestamp = _event_timestamp(row, board_type)

    desc_parts = [f"排名：{rank}"]
    if summary:
        desc_parts.append(summary)
    if category:
        desc_parts.append(f"分类：{category}")
    if installs is not None:
        desc_parts.append(f"近 30 天安装：{installs:,}")
    if trending is not None:
        desc_parts.append(f"趋势分：{trending:.2f}")
    if event_timestamp is not None:
        event_label = "上架" if board_type == "recently-added" else "更新"
        desc_parts.append(f"{event_label}：{_date(event_timestamp)}")
    if license_name:
        desc_parts.append(f"许可：{license_name}")
    if row.get("verification_verified") is True:
        desc_parts.append("开发者已验证")

    url = f"https://flathub.org/apps/{app_id}"
    hot = (
        round(trending)
        if board_type == "trending" and trending is not None
        else installs
    )
    return ListItem(
        id=app_id,
        title=name,
        author=developer or None,
        desc=" · ".join(desc_parts),
        hot=hot,
        cover=_text(row.get("icon")) or None,
        timestamp=event_timestamp,
        url=url,
        mobileUrl=url,
    )


def _event_timestamp(row: dict, board_type: str) -> int | None:
    if board_type == "recently-added":
        return _integer(row.get("added_at"))
    if board_type == "recently-updated":
        return _integer(row.get("updated_at"))
    return None


def _category_text(value: object) -> str:
    if isinstance(value, list):
        return "、".join(_text(item) for item in value if _text(item))
    return _text(value)


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    return round(number) if number is not None and number >= 0 else None


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
