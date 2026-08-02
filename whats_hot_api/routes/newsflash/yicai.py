from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_strings,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "yicai"

SOURCE_LINK = "https://www.yicai.com/brief/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "第一财经",
    "description": "第一财经 24 小时快讯",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="快讯",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://www.yicai.com/api/ajax/getbrieflist"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "page": "1",
            "pagesize": "20",
            "type": "0",
            "id": "0",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    items = result.data if isinstance(result.data, list) else []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("LiveTitle")) or text_or_none(it.get("NewsTitle"))
        content = strip_html(it.get("LiveContent") or it.get("newcontent") or title)
        if not title and not content:
            continue

        path = text_or_none(it.get("url"))
        detail_url = (
            f"https://www.yicai.com{path}"
            if path and path.startswith("/")
            else path
        )
        mobile_url = text_or_none(it.get("ShareUrl")) or detail_url or SOURCE_LINK
        detail_url = detail_url or mobile_url
        data.append(
            NewsFlashItem(
                id=str(it.get("LiveID") or it.get("id") or f"yicai-{len(data)}"),
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content),
                source="第一财经",
                isImportant=(
                    truthy_flag(it.get("IsImportant"))
                    or truthy_flag(it.get("important"))
                    or truthy_flag(it.get("istop"))
                ),
                tags=_split_tags(it.get("topics")),
                images=[
                    *_split_urls(it.get("LiveImages")),
                    *compact_urls(it.get("VideoThumb")),
                ],
                symbols=compact_objects(it.get("Stocks")),
                metrics=metrics(
                    liveWeight=to_int(it.get("LiveWeight")),
                    newsHot=to_int(it.get("NewsHot")),
                    countVotes=to_int(it.get("CountVotes")),
                    videoId=to_int(it.get("VideoID")),
                    interpretationStatus=to_int(it.get("interpretationStatus")),
                    openStockStyle=to_int(it.get("OpenStockStyle")),
                    relates=compact_objects(it.get("Relates")) or None,
                    votes=compact_strings(it.get("Votes")) or None,
                ),
                timestamp=get_time(it.get("CreateDate")),
                url=detail_url,
                mobileUrl=mobile_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _split_tags(value: object) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,，;；\s]+", str(value)):
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _split_urls(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return compact_urls(value)
    return compact_urls(re.split(r"[,，;；\s]+", str(value)))
