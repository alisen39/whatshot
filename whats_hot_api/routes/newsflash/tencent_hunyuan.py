from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post
from whats_hot_api.utils.newsflash import text_or_none

ROUTE_NAME = "tencent-hunyuan"
SOURCE_LINK = "https://hunyuan.tencent.com/research"
API_URL = "https://api.hunyuan.tencent.com/api/blog/publicList"
REQUEST_HEADERS = {"accept-language": "zh"}
REQUEST_BODY = {"pageNum": 1, "pageSize": 30}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "腾讯混元研究",
    "description": "腾讯混元官方最新模型、研究与发布动态",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="研究与发布",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await post(
        url=API_URL,
        headers=REQUEST_HEADERS,
        body=REQUEST_BODY,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_items(result.data),
    }


def _parse_items(payload: object) -> list[NewsFlashItem]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError("Tencent Hunyuan returned an unsuccessful response")

    response_data = payload.get("data")
    rows = response_data.get("list") if isinstance(response_data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Tencent Hunyuan returned an empty article list")

    items: list[NewsFlashItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = text_or_none(row.get("id"))
        title = text_or_none(row.get("title"))
        if not item_id or not title:
            continue

        summary = text_or_none(row.get("desc"))
        detail_url = _detail_url(row, item_id)
        items.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=summary or title,
                summary=summary,
                contentStatus="summary",
                source=text_or_none(row.get("author")) or "腾讯混元",
                timestamp=get_time(row.get("displayPublishTime")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    if not items:
        raise RuntimeError("Tencent Hunyuan response contains no usable articles")
    return items


def _detail_url(row: dict, item_id: str) -> str:
    custom_slug = text_or_none(row.get("customUrl"))
    slug = (
        custom_slug
        if custom_slug and re.fullmatch(r"[A-Za-z0-9._~-]+", custom_slug)
        else item_id
    )
    return f"{SOURCE_LINK}/{slug}"
