from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post
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

ROUTE_NAME = "jrj"

SOURCE_LINK = "https://24h.jrj.com.cn/newsFlash?jrjbq"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "金融界",
    "description": "金融界 24 小时快讯",
    "link": SOURCE_LINK,
}


_BEIJING = timezone(timedelta(hours=8))
_MAKE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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


async def _get_list(no_cache: bool, *, make_date: str | None = None) -> dict:
    url = "https://gateway.jrj.com/jrj-news/news/queryNewsFlash"
    result = await post(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        # makeDate pages strictly older than the given Beijing time.
        body={"makeDate": make_date} if make_date else {},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    raw = result.data or {}
    items = raw.get("data", {}).get("data") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title"))
        content = strip_html(it.get("detail") or it.get("summary") or title)
        if not title and not content:
            continue

        detail_url = (
            text_or_none(it.get("pcInfoUrl"))
            or text_or_none(it.get("infoUrl"))
            or SOURCE_LINK
        )
        mobile_url = (
            text_or_none(it.get("minfoUrl"))
            or text_or_none(it.get("infoUrl"))
            or detail_url
        )
        data.append(
            NewsFlashItem(
                id=str(it.get("iiId") or f"jrj-{len(data)}"),
                title=title or content[:60],
                content=content,
                summary=strip_html(it.get("summary")) or None,
                contentStatus=content_status(content),
                source=text_or_none(it.get("paperMediaSource")) or "金融界",
                isImportant=truthy_flag(it.get("isRed")),
                images=[
                    *compact_urls(it.get("imgUrl")),
                    *compact_urls(it.get("picThumb")),
                    *compact_urls(it.get("imageUrls")),
                ],
                symbols=compact_objects(it.get("stockList")),
                metrics=metrics(
                    readCount=to_int(it.get("readNum")),
                    channelNum=text_or_none(it.get("channelNum")),
                    infoCls=text_or_none(it.get("infoCls")),
                    aiScore=to_int(it.get("aiScore")),
                    hotValue=to_int(it.get("hotValue")),
                    emotion=text_or_none(it.get("emotion")),
                ),
                timestamp=get_time(it.get("makeDate")),
                url=detail_url,
                mobileUrl=mobile_url,
            )
        )
    make_dates = [str(it["makeDate"]) for it in items if it.get("makeDate")]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": raw,
        "oldest_make_date": min(make_dates) if make_dates else None,
    }


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before: datetime | None = None,
) -> BackfillPage:
    """Older pages by ``makeDate``; the upstream bound is exclusive, so the
    cursor moves one second past the oldest item to keep its second inclusive."""
    state = decode_cursor(cursor)
    make_date = state.get("makeDate")
    if make_date is None and before is not None:
        make_date = before.astimezone(_BEIJING).strftime(_MAKE_DATE_FORMAT)
    list_data = await _get_list(True, make_date=make_date)
    oldest = list_data["oldest_make_date"]
    next_cursor = None
    if oldest:
        bound = datetime.strptime(oldest, _MAKE_DATE_FORMAT) + timedelta(seconds=1)
        next_cursor = encode_cursor({"makeDate": bound.strftime(_MAKE_DATE_FORMAT)})
    page = _router_data(list_data)
    return BackfillPage(
        data=page.model_copy(update={"fromCache": False}),
        next_cursor=next_cursor,
        raw_digest=payload_digest(list_data["raw"]),
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.TIME_CURSOR,
        notes="queryNewsFlash：body.makeDate=上一页最老 makeDate（北京时间，含边界）；pageNum 无效；同秒条目需去重。",
        supports_before=True,
        verified_at="2026-10-14",
    ),
}
