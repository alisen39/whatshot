from __future__ import annotations

from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, strip_html
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
)

ROUTE_NAME = "qbitai-embodied"
SOURCE_LINK = "https://www.qbitai.com/tag/%E5%85%B7%E8%BA%AB%E6%99%BA%E8%83%BD"
FEED_URL = f"{SOURCE_LINK}/feed"
REQUEST_HEADERS = {"User-Agent": "WhatsHot/1.0"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "量子位 · 具身智能",
    "description": "量子位具身智能标签下的最新报道",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return _router_data(list_data)


def _router_data(list_data: dict) -> RouterData:
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="量子位资讯",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool, *, page: int = 1) -> dict:
    # WordPress feeds page with ?paged=N; page 1 keeps the plain realtime URL.
    result = await get(
        url=FEED_URL if page == 1 else f"{FEED_URL}?paged={page}",
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers=REQUEST_HEADERS,
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_feed(result.data),
    }


def _parse_feed(xml: str, *, limit: int | None = None) -> list[NewsFlashItem]:
    soup = BeautifulSoup(xml, "xml")
    rss = soup.find("rss")
    channel = rss.find("channel") if rss else None
    nodes = channel.find_all("item", recursive=False) if channel else []
    if not nodes:
        raise RuntimeError("QbitAI response is not a non-empty RSS feed")

    data: list[NewsFlashItem] = []
    for node in nodes:
        title = _tag_text(node, "title")
        detail_url = _absolute_url(_tag_text(node, "link"))
        if not title or not detail_url:
            continue

        description = strip_html(_tag_text(node, "description"))
        creator = _tag_text(node, "dc:creator")
        categories = compact_strings(
            [tag.get_text(" ", strip=True) for tag in node.find_all("category")]
        )
        item_id = _tag_text(node, "guid") or detail_url

        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=description or title,
                summary=description or None,
                contentStatus="summary",
                source=creator or "量子位",
                tags=categories,
                timestamp=_parse_pub_date(_tag_text(node, "pubDate")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    if not data:
        raise RuntimeError("QbitAI RSS contains no usable articles")
    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return data if limit is None else data[:limit]


def _tag_text(node, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _absolute_url(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text.startswith(("http://", "https://")) else None


def _parse_pub_date(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before=None,
) -> BackfillPage:
    """Older pages via the WordPress feed ``?paged=N``; past the end is empty or 404."""
    page = int(decode_cursor(cursor).get("page") or 1)
    try:
        list_data = await _get_list(True, page=page)
    except Exception:
        if page == 1:
            raise
        return BackfillPage(data=_router_data({"from_cache": False, "update_time": "", "data": []}), next_cursor=None)
    return BackfillPage(
        data=_router_data(list_data).model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"page": page + 1}) if list_data["data"] else None,
    )


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.PAGE_NUMBER,
        notes="标签 RSS feed?paged=N；10-14 实测列表新鲜度落后于生产所见，覆盖未证明。",
        verified_at="2026-10-14",
    ),
}
