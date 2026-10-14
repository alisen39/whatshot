from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import text_or_none
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
)

ROUTE_NAME = "caixin-data"

SOURCE_LINK = "https://cxdata.caixin.com/index/newsTab?tab=latest"
_API_URL = "https://cxdata.caixin.com/api/dataplus/sjtPc/news"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "财新数据通",
    "description": "财新数据通最新内容精选",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return _router_data(list_data)


def _router_data(list_data: dict) -> RouterData:
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="内容精选",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool, *, page: int = 1) -> dict:
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "pageNum": str(page),
            "pageSize": "100",
            "showLabels": "true",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    rows = ((result.data or {}).get("data") or {}).get("data") or []
    data: list[NewsFlashItem] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("flag") == "ad":
            continue
        title = text_or_none(row.get("title"))
        item_url = text_or_none(row.get("url"))
        if not title or not item_url:
            continue
        summary = text_or_none(row.get("summary"))
        tag = text_or_none(row.get("tag"))
        data.append(
            NewsFlashItem(
                id=_item_id(item_url),
                title=title,
                content=summary or title,
                summary=summary,
                contentStatus="summary",
                source=tag or "财新数据通",
                tags=[tag] if tag else [],
                images=[row["pic"]] if text_or_none(row.get("pic")) else [],
                timestamp=get_time(row.get("time")),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data[:100],
    }


def _item_id(url: str) -> str:
    query_id = (parse_qs(urlparse(url).query).get("id") or [None])[0]
    if query_id:
        return str(query_id)
    article_id = re.search(r"/(\d{7,})\.html", urlparse(url).path)
    if article_id:
        return article_id.group(1)
    return hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:20]


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Older pages via ``pageNum=N&pageSize=100`` (offset paging)."""
    page = int(decode_cursor(cursor).get("page") or 1)
    list_data = await _get_list(True, page=page)
    return BackfillPage(
        data=_router_data(list_data).model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"page": page + 1}) if list_data["data"] else None,
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.PAGE_NUMBER,
        notes="sjtPc/news?pageNum=N&pageSize=100。",
        page_size=100,
        verified_at="2026-10-14",
    ),
}
