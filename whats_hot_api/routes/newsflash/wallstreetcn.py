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
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
)
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
    unsupported,
)

ROUTE_NAME = "wallstreetcn"

list_type: dict[str, dict[str, str]] = {
    "global": {"name": "7x24快讯", "channel": "global-channel"},
    "a-stock": {"name": "A股", "channel": "a-stock-channel"},
    "us-stock": {"name": "美股", "channel": "us-stock-channel"},
    "hk-stock": {"name": "港股", "channel": "hk-stock-channel"},
    "forex": {"name": "外汇", "channel": "forex-channel"},
    "commodity": {"name": "商品", "channel": "commodity-channel"},
    "latest": {"name": "最新", "channel": "global-channel"},
    "hot": {"name": "最热", "channel": "global-channel"},
}

SOURCE_LINK = "https://wallstreetcn.com/live/global"

ROUTE_META: dict = {
    "name": "wallstreetcn",
    "title": "华尔街见闻",
    "description": "华尔街见闻 7x24 全球财经快讯",
    "params": {
        "type": {
            "name": "快讯频道",
            "type": {k: v["name"] for k, v in list_type.items()},
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "global")
    selected_type = type_param if type_param in list_type else "global"
    list_data = await _get_featured_list(selected_type, no_cache) if selected_type in {"latest", "hot"} else await _get_list(selected_type, no_cache)
    return _router_data(selected_type, list_data)


def _router_data(selected_type: str, list_data: dict) -> RouterData:
    type_info = list_type.get(selected_type, list_type["global"])
    return RouterData(
        kind="newsflash",
        **{**ROUTE_META, "type": type_info["name"]},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool, *, cursor: str | None = None) -> dict:
    type_info = list_type.get(type_param, list_type["global"])
    channel = type_info["channel"]
    url = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "channel": channel,
            "client": "pc",
            "limit": "50",
            # cursor = display_time bound, exclusive upstream.
            **({"cursor": cursor} if cursor else {}),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://wallstreetcn.com/live",
        },
    )

    raw_payload = result.data or {}
    items = raw_payload.get("data", {}).get("items") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = (it.get("title") or "").strip()
        body = (it.get("content_text") or strip_html(it.get("content"))).strip()
        if not title and not body:
            continue
        content = body or title
        uri = it.get("uri") or SOURCE_LINK
        author = it.get("author") if isinstance(it.get("author"), dict) else {}
        source = (
            text_or_none(it.get("reference"))
            or text_or_none(author.get("display_name"))
            or text_or_none(it.get("global_channel_name"))
        )
        score = it.get("score")
        data.append(
            NewsFlashItem(
                id=str(it.get("id") or f"wallstreetcn-{len(data)}"),
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content, has_more=it.get("content_more")),
                source=source,
                tags=compact_strings(it.get("tags")) or compact_strings(it.get("channels")),
                images=[
                    *compact_urls(it.get("cover_images")),
                    *compact_urls(it.get("images")),
                ],
                symbols=compact_objects(it.get("symbols")) + compact_objects(it.get("fund_codes")),
                metrics=metrics(
                    commentCount=to_int(it.get("comment_count")),
                    score=to_int(it.get("score")),
                ),
                # score>=2 在原站页面整条标红,score=1 或缺失是普通快讯
                isImportant=isinstance(score, int) and not isinstance(score, bool) and score >= 2,
                timestamp=get_time(it.get("display_time")),
                url=uri,
                mobileUrl=uri,
            )
        )
    times = [int(it["display_time"]) for it in items if it.get("display_time")]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": raw_payload,
        # +1 keeps the oldest second inclusive against the exclusive bound.
        "next": str(min(times) + 1) if times else None,
    }


async def _get_featured_list(board_type: str, no_cache: bool, *, cursor: str | None = None) -> dict:
    if board_type == "hot":
        url = "https://api-one.wallstcn.com/apiv1/content/articles/hot"
        params = {"period": "all"}
    else:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow"
        params = {"channel": "global-channel", "accept": "article", "limit": "30"}
        if cursor:
            # Older pages only answer on channel=global with action=upglide.
            params = {"channel": "global", "accept": "article", "limit": "30",
                      "cursor": cursor, "action": "upglide"}
    result = await get(
        url=url, params=params, no_cache=no_cache, ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json"},
    )
    raw = ((result.data or {}).get("data") or {}).get("day_items") if board_type == "hot" else ((result.data or {}).get("data") or {}).get("items") or []
    items: list[NewsFlashItem] = []
    for row in raw if isinstance(raw, list) else []:
        resource = row.get("resource") if isinstance(row, dict) else None
        source = resource if isinstance(resource, dict) else row if isinstance(row, dict) else {}
        if source.get("type") == "live" or row.get("resource_type") in {"theme", "ad"}:
            continue
        item_id = source.get("id")
        title = str(source.get("title") or source.get("content_short") or "").strip()
        content = strip_html(source.get("content") or source.get("content_short")).strip() or title
        uri = source.get("uri") or SOURCE_LINK
        if not item_id or not title:
            continue
        items.append(NewsFlashItem(
            id=str(item_id), title=title, content=content,
            contentStatus=content_status(content, fallback="summary"), source="华尔街见闻",
            tags=[list_type[board_type]["name"]], timestamp=get_time(source.get("display_time")),
            url=uri, mobileUrl=uri,
        ))
    next_cursor = ((result.data or {}).get("data") or {}).get("next_cursor") if raw else None
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items,
            "raw": result.data, "next": next_cursor or None}


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Lives page by display-time ``cursor``; ``latest`` follows information-flow ``next_cursor``."""
    selected_type = path_type if path_type in list_type else "global"
    upstream_cursor = decode_cursor(cursor).get("cursor")
    if selected_type == "latest":
        list_data = await _get_featured_list(selected_type, True, cursor=upstream_cursor)
    else:
        list_data = await _get_list(selected_type, True, cursor=upstream_cursor)
    next_value = list_data["next"]
    return BackfillPage(
        data=_router_data(selected_type, list_data).model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"cursor": next_value}) if next_value else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.OPAQUE_CURSOR,
        notes="lives 频道 cursor=上一页最老 display_time+1（上游不含边界，即 data.next_cursor+1）；最新文章 information-flow channel=global、action=upglide、next_cursor。",
        verified_at="2026-10-14",
    ),
    "hot": unsupported("推荐/排行成员与顺序无法按历史还原，只能读到当前内容。"),
}
