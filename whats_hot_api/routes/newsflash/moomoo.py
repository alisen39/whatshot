from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
)
from whats_hot_api.models import RouterData
from whats_hot_api.routes.newsflash.futunn import _get_list as _get_futu_list

ROUTE_NAME = "moomoo"

SOURCE_LINK = "https://www.moomoo.com/news/flash"
# Futu's international flash feed: same API as news.futunn.com (which 302s
# non-mainland IPs to /403 since 2026-09-11), but an English/global stream,
# not a mirror of the Chinese futunn board.
FLASH_API = "https://news.moomoo.com/news-site-api/main/get-flash-list"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "moomoo",
    "description": "moomoo 7x24 global flash news (English)",
    "link": SOURCE_LINK,
}


async def _get_list(no_cache: bool, *, seq_mark: str | None = None) -> dict:
    return await _get_futu_list(
        no_cache,
        seq_mark=seq_mark,
        api_url=FLASH_API,
        source_link=SOURCE_LINK,
        source_label="moomoo",
        id_prefix="moomoo",
    )


def _router_data(list_data: dict, *, from_cache: bool | None = None) -> RouterData:
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="Flash",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"] if from_cache is None else from_cache,
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    return _router_data(await _get_list(no_cache))


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
        data=_router_data(list_data, from_cache=False),
        next_cursor=encode_cursor({"seqMark": str(next_value)}) if next_value else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.OPAQUE_CURSOR,
        notes="get-flash-list（news.moomoo.com）：seqMark 取上游 data.data.seqMark；新加坡网络 2026-10-15 实测可翻页。",
        verified_at="2026-10-15",
    ),
}
