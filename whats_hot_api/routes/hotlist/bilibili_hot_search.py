from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bilibili-hot-search"

SOURCE_LINK = "https://search.bilibili.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "哔哩哔哩热搜",
    "description": "哔哩哔哩搜索热词",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热搜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://s.search.bilibili.com/main/hotword",
        no_cache=no_cache,
        response_type="json",
        params={"limit": "30"},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
        },
    )

    data: list[ListItem] = []
    for item in (result.data or {}).get("list") or []:
        keyword = (item.get("keyword") or "").strip()
        title = (item.get("show_name") or keyword).strip()
        if not keyword or not title:
            continue
        stat_data = item.get("stat_datas") if isinstance(item.get("stat_datas"), dict) else {}
        url = f"https://search.bilibili.com/all?keyword={quote(keyword)}"
        data.append(
            ListItem(
                id=str(item.get("hot_id") or keyword),
                title=title,
                cover=(item.get("icon") or "").replace("http:", "https:") or None,
                hot=item.get("heat_score") or item.get("score"),
                timestamp=get_time(stat_data.get("stime")),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
