from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bilibili-hot-video"

SOURCE_LINK = "https://www.bilibili.com/v/popular/all"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "哔哩哔哩热门视频",
    "description": "哔哩哔哩全站热门视频",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热门视频",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://api.bilibili.com/x/web-interface/popular",
        no_cache=no_cache,
        response_type="json",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
        },
    )

    data: list[ListItem] = []
    for item in (result.data or {}).get("data", {}).get("list") or []:
        bvid = item.get("bvid")
        title = (item.get("title") or "").strip()
        if not bvid or not title:
            continue
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        stat = item.get("stat") if isinstance(item.get("stat"), dict) else {}
        data.append(
            ListItem(
                id=str(bvid),
                title=title,
                desc=(item.get("desc") or "").strip() or None,
                cover=(item.get("pic") or "").replace("http:", "https:") or None,
                author=(owner.get("name") or "").strip() or None,
                timestamp=get_time(item.get("pubdate")),
                hot=stat.get("view") or stat.get("vv") or stat.get("like"),
                url=item.get("short_link_v2") or f"https://www.bilibili.com/video/{bvid}",
                mobileUrl=f"https://m.bilibili.com/video/{bvid}",
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
