from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import content_status
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
)

ROUTE_NAME = "mktnews-flash"
SOURCE_LINK = "https://mktnews.net/"
ROUTE_META = {"name": ROUTE_NAME, "title": "MKTNews · 快讯", "description": "MKTNews 实时财经快讯", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return (await _get_page(no_cache))["router_data"]


async def _get_page(no_cache: bool, *, last_id: str | None = None) -> dict:
    # last_id pages strictly older than that UUID; ids are opaque, never enumerated.
    params = {"type": "0", "limit": "50", **({"last_id": last_id} if last_id else {})}
    result = await get(url="https://api.mktnews.net/api/flash", params=params, no_cache=no_cache, ttl=config.NEWSFLASH_CACHE_TTL, response_type="json", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    rows = sorted((result.data or {}).get("data") or [], key=lambda row: get_time(row.get("time")) or 0, reverse=True)
    data: list[NewsFlashItem] = []
    for row in rows:
        payload = row.get("data") or {}
        content = str(payload.get("content") or "").strip()
        title = str(payload.get("title") or "").strip()
        match = re.match(r"^【([^】]*)】", content)
        title = title or (match.group(1) if match else content)
        item_id = row.get("id")
        if not title or not item_id:
            continue
        url = f"https://mktnews.net/flashDetail.html?id={item_id}"
        data.append(NewsFlashItem(id=item_id, title=title, content=content or title, contentStatus=content_status(content or title, fallback="summary"), source="MKTNews", isImportant=row.get("important") == 1, timestamp=get_time(row.get("time")), url=url, mobileUrl=url))
    router_data = RouterData(kind="newsflash", **ROUTE_META, type="快讯", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
    oldest = rows[-1].get("id") if rows else None
    return {"router_data": router_data, "raw": result.data, "next": oldest}


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Older pages via ``last_id`` = the previous page's oldest row id."""
    page = await _get_page(True, last_id=decode_cursor(cursor).get("lastId"))
    return BackfillPage(
        data=page["router_data"].model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"lastId": str(page["next"])}) if page["next"] else None,
        raw_digest=payload_digest(page["raw"]),
    )

# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.OPAQUE_CURSOR,
        notes="/api/flash：last_id=上一页最老行 UUID 原样；ID 不可枚举；time_start/time_end 语义未验证；本机网络 403，需在新加坡网络复测。",
        verified_at="2026-10-14",
    ),
}
