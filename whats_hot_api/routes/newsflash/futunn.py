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
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
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


FLASH_API = "https://news.futunn.com/news-site-api/main/get-flash-list"


async def _get_list(
    no_cache: bool,
    *,
    seq_mark: str | None = None,
    api_url: str = FLASH_API,
    source_link: str = SOURCE_LINK,
    source_label: str = "富途牛牛",
    id_prefix: str = "futunn",
) -> dict:
    """Shared by the moomoo route (same Futu flash API on its international host)."""
    url = api_url
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"pageSize": "50", **({"seqMark": seq_mark} if seq_mark else {})},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": source_link,
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

        detail_url = text_or_none(it.get("detailUrl")) or source_link
        level = to_int(it.get("level"))
        data.append(
            NewsFlashItem(
                id=str(it.get("newsUniqueId") or it.get("id") or f"{id_prefix}-{len(data)}"),
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content),
                source=source_label if id_prefix == "futunn" else (text_or_none(it.get("source")) or source_label),
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
        "raw": payload,
        "next": payload.get("data", {}).get("data", {}).get("seqMark") if items else None,
    }


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Older pages by echoing the upstream ``data.data.seqMark``."""
    list_data = await _get_list(True, seq_mark=decode_cursor(cursor).get("seqMark"))
    next_value = list_data["next"]
    return BackfillPage(
        data=RouterData(
            kind="newsflash",
            **ROUTE_META,
            type="快讯",
            total=len(list_data["data"]),
            fromCache=False,
            updateTime=list_data["update_time"],
            data=list_data["data"],
        ),
        next_cursor=encode_cursor({"seqMark": str(next_value)}) if next_value else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.OPAQUE_CURSOR,
        notes="get-flash-list：seqMark 取上游 data.data.seqMark。",
        verified_at="2026-10-14",
    ),
}
