from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

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
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
)

ROUTE_NAME = "jin10"

SOURCE_LINK = "https://www.jin10.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "金十数据",
    "description": "金十数据实时财经快讯",
    "link": SOURCE_LINK,
}

_TYPE_LABELS = {
    0: "快讯",
    1: "数据",
    2: "文章",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return _router_data(list_data)


def _router_data(list_data: dict) -> RouterData:
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="快讯",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool, *, max_time: str | None = None) -> dict:
    url = "https://flash-api.jin10.com/get_flash_list"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "channel": "-8200",
            "vip": "1",
            "num": "20",
            # max_time (Beijing "YYYY-mm-dd HH:MM:SS") is inclusive upstream.
            **({"max_time": max_time} if max_time else {}),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
            "Origin": SOURCE_LINK.rstrip("/"),
            "x-app-id": "bVBF4FyRTn5NJF5n",
            "x-version": "1.0.0",
        },
    )

    raw = result.data or {}
    items = raw.get("data") or []
    data: list[NewsFlashItem] = []
    for it in items:
        if not it.get("time"):
            continue
        raw = it.get("data") if isinstance(it.get("data"), dict) else {}
        content = strip_html(raw.get("content") or raw.get("title"))
        title = text_or_none(raw.get("title")) or _title_from_content(content)
        if not title and not content:
            continue

        item_id = text_or_none(it.get("id")) or f"jin10-{len(data)}"
        detail_url = (
            text_or_none(raw.get("source_link"))
            or f"https://flash.jin10.com/detail/{item_id}"
        )
        flash_type = to_int(it.get("type"))
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content),
                source=text_or_none(raw.get("source")) or "金十数据",
                isImportant=truthy_flag(it.get("important")),
                tags=compact_strings(it.get("tags")),
                images=compact_urls(raw.get("pic")),
                symbols=compact_objects(it.get("remark")),
                metrics=metrics(
                    flashType=flash_type,
                    flashTypeLabel=_TYPE_LABELS.get(flash_type or 0),
                    channels=it.get("channel"),
                    voiceStatus=text_or_none(it.get("voice_status")),
                    ad=(
                        it.get("extras", {}).get("ad")
                        if isinstance(it.get("extras"), dict)
                        else None
                    ),
                ),
                timestamp=get_time(it.get("time")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    times = [str(it["time"]) for it in items if it.get("time")]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": raw,
        "oldest_time": min(times) if times else None,
    }


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before: datetime | None = None,
) -> BackfillPage:
    """Older pages with ``max_time`` = previous page's oldest time (inclusive)."""
    state = decode_cursor(cursor)
    max_time = state.get("maxTime")
    if max_time is None and before is not None:
        max_time = before.astimezone(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    list_data = await _get_list(True, max_time=max_time)
    oldest = list_data["oldest_time"]
    return BackfillPage(
        data=_router_data(list_data).model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"maxTime": oldest}) if oldest else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


_BEIJING = timezone(timedelta(hours=8))


def _title_from_content(content: str) -> str | None:
    match = re.match(r"^【(.+?)】", content)
    return match.group(1).strip() if match else None


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.TIME_CURSOR,
        notes="get_flash_list：max_time=上一页最老 time 的北京时间字符串（含边界），保留 channel/vip。",
        supports_before=True,
        verified_at="2026-10-14",
    ),
}
