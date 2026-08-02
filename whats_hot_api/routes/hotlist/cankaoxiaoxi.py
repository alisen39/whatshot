from __future__ import annotations

import asyncio

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "cankaoxiaoxi"

SOURCE_LINK = "https://china.cankaoxiaoxi.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "参考消息",
    "description": "参考消息网新闻资讯",
    "link": SOURCE_LINK,
}

_CHANNELS = ("zhongguo", "guandian", "gj")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="资讯",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    results = await asyncio.gather(
        *[
            get(
                url=f"https://china.cankaoxiaoxi.com/json/channel/{channel}/list.json",
                no_cache=no_cache,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": SOURCE_LINK,
                },
            )
            for channel in _CHANNELS
        ]
    )

    data: list[ListItem] = []
    for result in results:
        for row in (result.data or {}).get("list") or []:
            item = row.get("data") if isinstance(row.get("data"), dict) else {}
            title = (item.get("title") or "").strip()
            url = (item.get("url") or item.get("otherUrl") or "").strip()
            if not title or not url:
                continue
            timestamp = get_time(item.get("publishTime") or item.get("lastpublishTime"))
            hot = _hot_score(item)
            data.append(
                ListItem(
                    id=str(item.get("id") or url),
                    title=title,
                    cover=item.get("mCoverImg_s") or item.get("mCoverImg") or None,
                    author=(item.get("channelName") or "").strip() or None,
                    desc=(item.get("description") or "").strip() or None,
                    hot=hot,
                    timestamp=timestamp,
                    url=url,
                    mobileUrl=url,
                )
            )

    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    update_time = max((result.update_time for result in results), default="")
    return {
        "from_cache": all(result.from_cache for result in results),
        "update_time": update_time,
        "data": data,
    }


def _hot_score(item: dict) -> int | None:
    total = 0
    for key in ("commentCount", "praiseCount", "visitCount", "initvisitCount"):
        try:
            total += int(item.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total or None
