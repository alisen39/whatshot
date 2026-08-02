from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_strings,
    compact_urls,
    metrics,
    strip_html,
    text_or_none,
    truthy_flag,
)

ROUTE_NAME = "spaceflight-news"

SOURCE_LINK = "https://spaceflightnewsapi.net/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Spaceflight News",
    "description": "全球航天与太空产业最新新闻",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="航天新闻",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://api.spaceflightnewsapi.net/v4/articles/"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"limit": "15"},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    items = (result.data or {}).get("results") or []
    data: list[NewsFlashItem] = []
    for item in items:
        title = text_or_none(item.get("title"))
        summary = strip_html(item.get("summary"))
        detail_url = text_or_none(item.get("url"))
        if not title or not detail_url:
            continue

        data.append(
            NewsFlashItem(
                id=str(item.get("id") or detail_url),
                title=title,
                content=summary or title,
                summary=summary or None,
                contentStatus="summary",
                source=text_or_none(item.get("news_site")) or "Spaceflight News",
                isImportant=truthy_flag(item.get("featured")),
                tags=compact_strings(item.get("authors")),
                images=compact_urls(item.get("image_url")),
                symbols=(
                    compact_objects(item.get("launches"))
                    + compact_objects(item.get("events"))
                ),
                metrics=metrics(updatedAt=text_or_none(item.get("updated_at"))),
                timestamp=get_time(item.get("published_at")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
