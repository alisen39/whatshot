from __future__ import annotations

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

ROUTE_NAME = "jrj"

SOURCE_LINK = "https://24h.jrj.com.cn/newsFlash?jrjbq"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "金融界",
    "description": "金融界 24 小时快讯",
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


async def _get_list(no_cache: bool) -> dict:
    url = "https://gateway.jrj.com/jrj-news/news/queryNewsFlash"
    result = await post(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        body={},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    items = (result.data or {}).get("data", {}).get("data") or []
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
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
