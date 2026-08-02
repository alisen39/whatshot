from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "packagist"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Packagist",
    "description": "Packagist 最近一周下载热度最高的 Composer 软件包",
    "link": "https://packagist.org/explore/popular",
}

_POPULAR_URL = "https://packagist.org/explore/popular.json"
_MAX_ITEMS = 100


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="本周热门",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_POPULAR_URL,
        params={"per_page": str(_MAX_ITEMS)},
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{_POPULAR_URL}?per_page={_MAX_ITEMS}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = (result.data or {}).get("packages", [])
    data = [
        item
        for rank, row in enumerate(rows[:_MAX_ITEMS], start=1)
        if (item := _package_item(row, rank)) is not None
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _package_item(row: object, rank: int) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    name = _text(row.get("name"))
    url = _text(row.get("url"))
    if not name or not url:
        return None

    description = _text(row.get("description"))
    downloads = _integer(row.get("downloads"))
    favers = _integer(row.get("favers"))
    desc_parts = [f"本周热度排名：{rank}"]
    if description:
        desc_parts.append(description)
    if downloads is not None:
        desc_parts.append(f"累计下载：{downloads:,}")
    if favers is not None:
        desc_parts.append(f"收藏：{favers:,}")

    return ListItem(
        id=name,
        title=name,
        desc=" · ".join(desc_parts),
        hot=downloads,
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
