from __future__ import annotations

import time

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "jiemian"

SOURCE_LINK = "https://www.jiemian.com/lists/4.html"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "界面新闻",
    "description": "界面新闻 7x24 实时快讯",
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
    url = "https://papi.jiemian.com/page/api/kuaixun/getLastest"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "cid": "1323kb",
            "tagid": "1323",
            "end_time": str(int(time.time()) - 86400),
        },
        cache_key=f"{url}?cid=1323kb&tagid=1323&window=latest",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    payload = result.data or {}
    items = payload.get("result") or []
    items = sorted(
        items,
        key=lambda item: to_int(item.get("publishtime")) or 0,
        reverse=True,
    )[:50]

    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title"))
        content = strip_html(it.get("summary") or title)
        if not title and not content:
            continue

        article_id = text_or_none(it.get("id"))
        detail_url = (
            f"https://www.jiemian.com/article/{article_id}.html"
            if article_id
            else SOURCE_LINK
        )
        weight = text_or_none(it.get("weights"))
        data.append(
            NewsFlashItem(
                id=article_id or f"jiemian-{len(data)}",
                title=title or content[:60],
                content=content,
                summary=content if content and content != title else None,
                contentStatus=content_status(content, fallback="summary"),
                source="界面新闻",
                isImportant=weight in {"A", "B"} or truthy_flag(it.get("is_make_img")),
                images=compact_urls(it.get("img_urls")),
                metrics=metrics(
                    weight=weight,
                    isMakeImg=to_int(it.get("is_make_img")),
                    editCms=to_int(it.get("edit_cms")),
                    blackwhite=to_int(it.get("blackwhite")),
                ),
                timestamp=get_time(it.get("publishtime")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
