from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "tencent-hot"

SOURCE_LINK = "https://news.qq.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "腾讯热点",
    "description": "腾讯新闻综合热点资讯",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热点",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://i.news.qq.com/web_backend/v2/getTagInfo"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params={"tagId": "aEWqxLtdgmQ="},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    tabs = (result.data or {}).get("data", {}).get("tabs") or []
    items = tabs[0].get("articleList") if tabs else []
    data: list[ListItem] = []
    for item in items or []:
        title = (item.get("title") or "").strip()
        link_info = item.get("link_info") if isinstance(item.get("link_info"), dict) else {}
        url_value = link_info.get("url") or link_info.get("share_url") or ""
        if not title or not url_value:
            continue
        media_info = item.get("media_info") if isinstance(item.get("media_info"), dict) else {}
        interaction = (
            item.get("interation_info")
            if isinstance(item.get("interation_info"), dict)
            else {}
        )
        data.append(
            ListItem(
                id=str(item.get("id") or url_value),
                title=title,
                cover=_cover(item.get("pic_info")),
                author=(media_info.get("chl_name") or "").strip() or None,
                desc=(item.get("desc") or item.get("long_summary") or "").strip() or None,
                hot=interaction.get("read_num") or interaction.get("commet_num"),
                timestamp=get_time(item.get("publish_time") or item.get("update_time")),
                url=url_value,
                mobileUrl=link_info.get("share_url") or url_value,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _cover(pic_info: object) -> str | None:
    if not isinstance(pic_info, dict):
        return None
    for key in ("share_img", "big_img", "small_img", "three_img"):
        value = pic_info.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value:
            return value
    ext = pic_info.get("ext")
    if isinstance(ext, dict):
        for value in ext.values():
            if value:
                return str(value)
    return None
