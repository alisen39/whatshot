from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "futunn"

SOURCE_LINK = "https://news.futunn.com/flash"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "富途牛牛",
    "description": "富途牛牛 7x24 快讯",
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
    url = "https://news.futunn.com/news-site-api/main/get-flash-list"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"pageSize": "50"},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    payload = result.data or {}
    items = payload.get("data", {}).get("data", {}).get("news") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title"))
        content = strip_html(it.get("content") or title)
        if not title and not content:
            continue

        detail_url = text_or_none(it.get("detailUrl")) or SOURCE_LINK
        level = to_int(it.get("level"))
        data.append(
            NewsFlashItem(
                id=str(it.get("newsUniqueId") or it.get("id") or f"futunn-{len(data)}"),
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content),
                source="富途牛牛",
                isImportant=truthy_flag(level),
                images=compact_urls(it.get("pic")),
                symbols=compact_objects(it.get("relatedStocks")) + compact_objects(it.get("quote")),
                metrics=metrics(
                    level=level,
                    newsType=to_int(it.get("newsType")),
                    newsContentType=to_int(it.get("newsContentType")),
                    sourceId=to_int(it.get("sourceId")),
                    isAutoTranslated=to_int(it.get("isAutoTranslated")),
                ),
                timestamp=get_time(it.get("time")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
