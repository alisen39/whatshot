from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "crates"

type_map: dict[str, str] = {
    "downloads": "累计下载",
    "recent-downloads": "近期下载",
    "recent-updates": "最近更新",
    "new": "新发布",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "crates.io",
    "description": "crates.io Rust 软件包下载与发布榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://crates.io/",
}

_API_URL = "https://crates.io/api/v1/crates"
_MAX_ITEMS = 20


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "downloads")
    selected_type = type_param if type_param in type_map else "downloads"
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
        url=_API_URL,
        params={
            "page": "1",
            "per_page": str(_MAX_ITEMS),
            "sort": board_type,
        },
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{_API_URL}?page=1&per_page={_MAX_ITEMS}&sort={board_type}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = (result.data or {}).get("crates", [])
    data = [
        item
        for rank, row in enumerate(rows[:_MAX_ITEMS], start=1)
        if (item := _crate_item(row, rank, board_type)) is not None
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _crate_item(row: object, rank: int, board_type: str) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    crate_id = _text(row.get("id") or row.get("name"))
    name = _text(row.get("name") or row.get("id"))
    if not crate_id or not name:
        return None

    version = _text(
        row.get("newest_version")
        or row.get("max_stable_version")
        or row.get("max_version")
    )
    description = _text(row.get("description"))
    downloads = _integer(row.get("downloads"))
    recent_downloads = _integer(row.get("recent_downloads"))
    updated_at = _text(row.get("updated_at"))
    created_at = _text(row.get("created_at"))

    desc_parts = [f"排名：{rank}"]
    if version:
        desc_parts.append(f"版本：{version}")
    if description:
        desc_parts.append(description)
    if downloads is not None:
        desc_parts.append(f"累计下载：{downloads:,}")
    if recent_downloads is not None:
        desc_parts.append(f"近期下载：{recent_downloads:,}")

    if board_type == "new":
        timestamp = get_time(created_at or None)
    elif board_type == "recent-updates":
        timestamp = get_time(updated_at or None)
    else:
        timestamp = None
    hot = recent_downloads if board_type == "recent-downloads" else downloads
    url = f"https://crates.io/crates/{crate_id}"
    return ListItem(
        id=crate_id,
        title=name,
        desc=" · ".join(desc_parts),
        hot=hot,
        timestamp=timestamp,
        url=url,
        mobileUrl=url,
    )


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
