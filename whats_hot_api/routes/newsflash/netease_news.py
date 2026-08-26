from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import text_or_none

ROUTE_NAME = "netease-news"
SOURCE_LINK = "https://m.163.com/hot"
API_URL = "https://m.163.com/fe/api/hot/news/flow"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "网易新闻",
    "description": "网易新闻最新内容流",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
    )
    data = _parse_items(result.data)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="最新内容",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _parse_items(payload: object) -> list[NewsFlashItem]:
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise RuntimeError("NetEase News returned an unsuccessful response")

    response_data = payload.get("data")
    rows = response_data.get("list") if isinstance(response_data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("NetEase News returned an empty article list")

    items: list[NewsFlashItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = _stable_id(row)
        title = text_or_none(row.get("title"))
        detail_url = _absolute_url(row.get("url"))
        if not item_id or not title or not detail_url:
            continue

        image = _absolute_url(row.get("imgsrc"))
        items.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=title,
                contentStatus="summary",
                source=text_or_none(row.get("source")) or "网易新闻",
                images=[image] if image else [],
                timestamp=get_time(row.get("ptime") or row.get("publishTime")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    if not items:
        raise RuntimeError("NetEase News response contains no usable articles")
    return items


def _absolute_url(value: object) -> str | None:
    text = text_or_none(value)
    return text if text and text.startswith(("http://", "https://")) else None


def _stable_id(row: dict) -> str | None:
    document_id = text_or_none(row.get("docid"))
    if document_id:
        return document_id
    if row.get("skipType") == "video":
        return text_or_none(row.get("skipID") or row.get("vid"))
    return None
