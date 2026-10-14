from __future__ import annotations

import re
import time

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

ROUTE_NAME = "gelonghui"

SOURCE_LINK = "https://www.gelonghui.com/live"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "格隆汇",
    "description": "格隆汇 7x24 实时财经快讯",
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


async def _get_list(no_cache: bool, *, live_id: str | None = None) -> dict:
    url = "https://www.gelonghui.com/api/live-channels/all/lives/v4"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "category": "all",
            "limit": "20",
            "timestamp": str(int(time.time() * 1000)),
            # liveId pages strictly older than that live item; timestamp is only a refresh nonce.
            **({"liveId": live_id} if live_id else {}),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    items = (result.data or {}).get("result") or []
    data: list[NewsFlashItem] = []
    for it in items:
        content = strip_html(it.get("content") or "")
        title = text_or_none(it.get("title")) or _title_from_content(content)
        if not title and not content:
            continue

        source_obj = it.get("source") if isinstance(it.get("source"), dict) else {}
        count_obj = it.get("count") if isinstance(it.get("count"), dict) else {}
        level = to_int(it.get("level"))
        detail_url = text_or_none(it.get("route")) or SOURCE_LINK
        data.append(
            NewsFlashItem(
                id=str(it.get("id") or f"gelonghui-{len(data)}"),
                title=title or content[:60],
                content=content or title or "",
                contentStatus=content_status(content),
                source=text_or_none(source_obj.get("name")) or "格隆汇",
                isImportant=truthy_flag(level),
                images=compact_urls(it.get("pictures")),
                symbols=compact_objects(it.get("relatedStocks")),
                metrics=metrics(
                    level=level,
                    readCount=to_int(count_obj.get("read")),
                    commentCount=to_int(count_obj.get("comment")),
                    favoriteCount=to_int(count_obj.get("favorite")),
                    likeCount=to_int(count_obj.get("like")),
                    shareCount=to_int(count_obj.get("share")),
                ),
                timestamp=get_time(it.get("createTimestamp")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": result.data,
        "next": items[-1].get("id") if items else None,
    }


def _title_from_content(content: str) -> str | None:
    match = re.match(r"^【(.+?)】", content)
    return match.group(1).strip() if match else None


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Older pages via ``liveId`` = the previous page's last (oldest) live id."""
    list_data = await _get_list(True, live_id=decode_cursor(cursor).get("liveId"))
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
        next_cursor=encode_cursor({"liveId": str(next_value)}) if next_value else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.OPAQUE_CURSOR,
        notes="lives/v4：liveId=上一页末条 ID；timestamp 仅为刷新参数。",
        verified_at="2026-10-14",
    ),
}
