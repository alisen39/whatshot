from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "apple-podcasts"

type_map: dict[str, str] = {
    "cn": "中国区 Top 100",
    "us": "美国区 Top 100",
    "gb": "英国区 Top 100",
    "jp": "日本区 Top 100",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Apple Podcasts",
    "description": "Apple Podcasts 各地区热门播客榜",
    "params": {
        "type": {
            "name": "地区",
            "type": type_map,
        },
    },
    "link": "https://podcasts.apple.com/cn/charts",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "cn")
    selected_type = type_param if type_param in type_map else "cn"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **{
            **ROUTE_META,
            "link": f"https://podcasts.apple.com/{selected_type}/charts",
        },
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(country: str, no_cache: bool) -> dict:
    result = await get(
        url=(
            "https://rss.marketingtools.apple.com/api/v2/"
            f"{country}/podcasts/top/100/podcasts.json"
        ),
        no_cache=no_cache,
        headers={"Accept": "application/json"},
    )
    items = result.data.get("feed", {}).get("results", [])
    data: list[ListItem] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("name") or "").strip()
        item_url = str(item.get("url") or "").strip()
        if not item_id or not title or not item_url:
            continue
        genres = [
            str(genre.get("name") or "").strip()
            for genre in item.get("genres", [])
            if isinstance(genre, dict) and str(genre.get("name") or "").strip()
        ]
        data.append(
            ListItem(
                id=item_id,
                title=title,
                author=item.get("artistName"),
                desc="、".join(genres) or None,
                cover=item.get("artworkUrl100"),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
