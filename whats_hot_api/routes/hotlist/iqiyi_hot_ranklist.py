from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "iqiyi-hot-ranklist"

SOURCE_LINK = "https://www.iqiyi.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "爱奇艺热播榜",
    "description": "爱奇艺热门视频榜",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热播榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://mesh.if.iqiyi.com/portal/lw/v7/channel/card/videoTab"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params={
            "channelName": "recommend",
            "data_source": "v7_rec_sec_hot_rank_list",
            "tempId": "85",
            "count": "30",
            "block_id": "hot_ranklist",
            "device": "14a4b5ba98e790dce6dc07482447cf48",
            "from": "webapp",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    containers = (result.data or {}).get("items") or []
    videos = containers[0].get("video") if containers else []
    items = videos[0].get("data") if videos else []
    data: list[ListItem] = []
    for item in items or []:
        title = (item.get("title") or item.get("display_name") or "").strip()
        url_value = (item.get("page_url") or "").strip()
        if not title or not url_value:
            continue
        data.append(
            ListItem(
                id=str(item.get("entity_id") or item.get("tv_id") or url_value),
                title=title,
                cover=(
                    item.get("image_url_normal")
                    or item.get("image_cover")
                    or item.get("album_image_url_hover")
                ),
                author=_names(item.get("starring") or item.get("contributor")) or None,
                desc=(item.get("desc") or item.get("description") or "").strip() or None,
                hot=item.get("hot_score") or item.get("playCnt"),
                timestamp=_show_date(item),
                url=url_value,
                mobileUrl=url_value,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _names(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names = [
        str(item.get("name")).strip()
        for item in value
        if isinstance(item, dict) and item.get("name")
    ]
    return " / ".join(names[:5])


def _show_date(item: dict) -> int | None:
    date_obj = item.get("date")
    if isinstance(date_obj, dict):
        year = date_obj.get("year")
        month = date_obj.get("month")
        day = date_obj.get("day")
        if year and month and day:
            return get_time(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    return get_time(item.get("showDate"))
