from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, strip_html, text_or_none

ROUTE_NAME = "xuangubao"

SOURCE_LINK = "https://xuangutong.com.cn/ts"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "选股宝",
    "description": "选股宝最新投资研报",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="研报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://baoer-api.xuangubao.com.cn/api/v6/report/reports/list"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "limit": "20",
            "tag_ids": "",
            "category_ids": "",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://xuangutong.com.cn/",
            "x-appgo-platform": "device=pc",
            "x-track-info": '{"AppId":"com.xuangutong.web","AppVersion":"1.0.0"}',
        },
    )

    payload = result.data or {}
    items = (payload.get("data") or {}).get("items") or []
    data: list[NewsFlashItem] = []
    for item in items:
        title = text_or_none(item.get("title"))
        summary = strip_html(item.get("summary"))
        if not title and not summary:
            continue

        detail_url = text_or_none(item.get("route")) or SOURCE_LINK
        organizations = compact_strings(item.get("organizations"))
        data.append(
            NewsFlashItem(
                id=str(item.get("id") or f"xuangubao-{len(data)}"),
                title=title or summary[:60],
                content=summary or title or "",
                summary=summary or None,
                contentStatus="summary",
                source="、".join(organizations) or "选股宝",
                tags=compact_strings(item.get("tags")),
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
