from __future__ import annotations

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "steam"

SOURCE_LINK = "https://store.steampowered.com/stats/stats/"

type_map: dict[str, str] = {
    "players": "在线人数榜",
    "top-sellers": "热销商品榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Steam",
    "description": "Steam 在线人数与热销商品排行榜",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "players")
    selected_type = type_param if type_param in type_map else "players"
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
    if board_type == "top-sellers":
        return await _get_top_sellers(no_cache)
    return await _get_players(no_cache)


async def _get_players(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    for row in soup.select("#detailStats tr.player_count_row"):
        anchor = row.select_one("a.gameLink")
        current = row.select_one("td:first-child .currentServers")
        peak = row.select_one("td:nth-child(2) .currentServers")
        if anchor is None or current is None:
            continue
        title = anchor.get_text(" ", strip=True)
        item_url = str(anchor.get("href") or "").strip()
        current_text = current.get_text(" ", strip=True)
        if not title or not item_url or not current_text:
            continue
        current_players = _player_count(current_text)
        peak_text = peak.get_text(" ", strip=True) if peak else ""
        description = f"当前在线 {current_text}"
        if peak_text:
            description += f"；今日峰值 {peak_text}"
        data.append(
            ListItem(
                id=_steam_app_id(item_url) or item_url,
                title=title,
                hot=current_players,
                desc=description,
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_top_sellers(no_cache: bool) -> dict:
    url = "https://store.steampowered.com/api/featuredcategories/"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params={"cc": "cn", "l": "schinese"},
        cache_key=f"{url}?cc=cn&l=schinese",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    rows = ((result.data or {}).get("top_sellers") or {}).get("items") or []
    data: list[ListItem] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        item_id = str(row.get("id") or "").strip()
        title = str(row.get("name") or "").strip()
        item_type = int(row.get("type") or 0)
        identity = (item_type, item_id)
        if not item_id or not title or identity in seen:
            continue
        seen.add(identity)
        path = "sub" if item_type == 1 else "app"
        item_url = f"https://store.steampowered.com/{path}/{item_id}/"
        desc_parts = []
        if row.get("final_price") is not None:
            desc_parts.append(f"售价：¥{int(row['final_price']) / 100:.2f}")
        if row.get("discount_percent"):
            desc_parts.append(f"优惠：{row['discount_percent']}%")
        data.append(
            ListItem(
                id=f"{path}:{item_id}",
                title=title,
                desc=" · ".join(desc_parts) or None,
                cover=str(row.get("header_image") or "").strip() or None,
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _player_count(value: str) -> int | None:
    try:
        return int(value.replace(",", "").strip())
    except ValueError:
        return None


def _steam_app_id(url: str) -> str | None:
    marker = "/app/"
    if marker not in url:
        return None
    app_id = url.split(marker, 1)[1].split("/", 1)[0]
    return app_id or None
