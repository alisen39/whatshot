from __future__ import annotations

import json
from datetime import datetime
import re
from urllib.parse import urljoin

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.http_client import get, post
from whats_hot_api.utils.newsflash import content_status, to_int
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    payload_digest,
    unsupported,
)

ROUTE_NAME = "fastbull"

SOURCE_LINK = "https://www.fastbull.com/"
# The express feed is the fastbull-news-service JSON gateway behind the FastBull
# apps and the .cn homepage ticker. The api.fastbull.cn host serves the zh
# edition; api.fastbull.com serves the en edition (pinned via the verified
# lang: en-us header; api.fastbull.cn is zh-locked and ignores lang headers).
# The zh and en editions are parallel translations with disjoint ID namespaces.
# The legacy .com SSR page now 302s CN clients to the .cn trading site, so the
# JSON feeds are the geo-independent source of truth for flash boards.
FEED_URL_ZH = "https://api.fastbull.cn/fastbull-news-service/api/getNewsPageByTagIds"
FEED_URL_EN = "https://api.fastbull.com/fastbull-news-service/api/getNewsPageByTagIds"
FEED_PAGE_SIZE = 50
FLASH_ID_PREFIX = "/cn/fastshort/"
EN_FLASH_ID_PREFIX = "/fastshort/"
TYPE_MAP = {
    "express": "快讯",
    "important": "重要快讯",
    "en": "英文快讯",
    "news": "头条",
}
# The .cn host returns no articles for this endpoint. Pin the Chinese edition
# on .com and select news only (1); analyst (2) and institution (5) are separate.
NEWS_URL = "https://api.fastbull.com/fastbull-news-service/api/getNewsPageOrderByTimeDesc"
_NATIVE_ID_RE = re.compile(r"\d+(?:_\d+)*")
FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.fastbull.cn/",
}
FEED_HEADERS_EN = {
    **FEED_HEADERS,
    "Referer": "https://www.fastbull.com/",
    # Verified edition pin: en-us equals the .com default; zh-cn would switch
    # this host to the zh edition.
    "lang": "en-us",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "法布财经",
    "description": "法布财经实时市场快讯与财经头条",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "快讯分类", "type": TYPE_MAP}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "express")
    board_type = requested_type if requested_type in TYPE_MAP else "express"
    if board_type == "news":
        list_data = await _get_news_list(no_cache)
    else:
        list_data = await _get_feed_list(board_type, no_cache)
    return _router_data(board_type, list_data)


def _router_data(board_type: str, list_data: dict) -> RouterData:
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_feed_list(board_type: str, no_cache: bool, *, timestamp: int | None = None) -> dict:
    if board_type == "en":
        url, headers = FEED_URL_EN, FEED_HEADERS_EN
        params = {"pageSize": str(FEED_PAGE_SIZE)}
    else:
        url, headers = FEED_URL_ZH, FEED_HEADERS
        params = {
            "pageSize": str(FEED_PAGE_SIZE),
            "checkImportant": "1" if board_type == "important" else "0",
        }
    if timestamp is not None:
        # releasedDate bound in ms, inclusive upstream.
        params["timestamp"] = str(timestamp)
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params=params,
        headers=headers,
    )
    envelope = result.data
    if not isinstance(envelope, dict) or envelope.get("code") != 0:
        raise ValueError("FastBull feed envelope is not a success response")
    body = envelope.get("bodyMessage")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as error:
        raise ValueError("FastBull feed bodyMessage is not valid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("pageDatas"), list):
        # Invalid upstream params (e.g. bad pageSize) also land here with
        # bodyMessage null; treat both as an incompatible feed, not an empty list.
        raise ValueError("FastBull feed is missing its pageDatas list")  # noqa: TRY004 - invalid upstream data
    data: list[NewsFlashItem] = []
    seen: set[str] = set()
    for node in payload["pageDatas"]:
        if not isinstance(node, dict):
            raise ValueError("FastBull feed row is not an object")  # noqa: TRY004 - invalid upstream data
        native_id = str(node.get("path") or "")
        if not _NATIVE_ID_RE.fullmatch(native_id):
            raise ValueError("FastBull flash is missing its native id")
        item_id = (EN_FLASH_ID_PREFIX if board_type == "en" else FLASH_ID_PREFIX) + native_id
        if item_id in seen:
            continue
        title = _text(node.get("newsTitle"))
        if not title:
            continue
        if board_type == "important" and node.get("important") != 1:
            # The gateway has silently ignored request filters before
            # (tagIds[]), so enforce the board semantics locally.
            continue
        seen.add(item_id)
        url = urljoin(SOURCE_LINK, item_id)
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                # A flash row carries the complete public update text in
                # newsTitle; there is no separate summary field upstream.
                content=title,
                summary=None,
                contentStatus=content_status(title, fallback="full"),
                source="法布财经",
                tags=[TYPE_MAP[board_type]],
                isImportant=node.get("important") == 1,
                timestamp=to_int(node.get("releasedDate")),
                url=url,
                mobileUrl=url,
            )
        )
    if not data and board_type != "important" and timestamp is None:
        raise ValueError("FastBull express feed is empty")
    # The important board filters to important==1 flashes, so an empty page is
    # a legitimate quiet-window state there; express and en must never be empty.
    # An empty historical page is the end of the upstream window.
    released = [to_int(node.get("releasedDate")) for node in payload["pageDatas"]]
    released = [value for value in released if value]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": payload,
        "next": min(released) if released else None,
    }


async def _get_news_list(no_cache: bool, *, timestamp: int | None = None) -> dict:
    result = await post(
        url=NEWS_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        headers={"lang": "zh-cn"},
        body={
            "pageSize": FEED_PAGE_SIZE,
            "showNewsTypeList": [1],
            # pubTime bound in ms, exclusive upstream.
            **({"timestamp": timestamp} if timestamp is not None else {}),
        },
    )
    envelope = result.data
    if not isinstance(envelope, dict) or envelope.get("code") != 0:
        raise ValueError("FastBull news envelope is not a success response")
    body = envelope.get("bodyMessage")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as error:
        raise ValueError("FastBull news bodyMessage is not valid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("pageDatas"), list):
        raise ValueError("FastBull news is missing its pageDatas list")  # noqa: TRY004 - invalid upstream data
    data: list[NewsFlashItem] = []
    seen: set[str] = set()
    for node in payload["pageDatas"]:
        if not isinstance(node, dict):
            raise ValueError("FastBull news row is not an object")  # noqa: TRY004 - invalid upstream data
        if node.get("langId") != 1 or node.get("showNewsType") != 1:
            raise ValueError("FastBull news has an unexpected language or article type")
        native_id = str(node.get("path") or "")
        if not _NATIVE_ID_RE.fullmatch(native_id):
            raise ValueError("FastBull article is missing its native id")
        if node.get("originalStatus") not in (0, 1):
            raise ValueError("FastBull article has an invalid detail URL variant")
        item_id = f"/cn/news-detail/{native_id}"
        if item_id in seen:
            continue
        title = _text(node.get("title"))
        if not title:
            continue
        timestamp = to_int(node.get("pubTime"))
        if timestamp is None or timestamp < 1_000_000_000_000:
            raise ValueError("FastBull article is missing its publication time in milliseconds")
        seen.add(item_id)
        detail = "newsdetail" if node["originalStatus"] == 1 else "news-detail"
        url = urljoin(SOURCE_LINK, f"/cn/{detail}/{native_id}")
        summary = _text(node.get("summary")) or _text(node.get("brief"))
        content = summary or title
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=content,
                summary=summary or None,
                contentStatus=content_status(content, fallback="summary"),
                source="法布财经",
                tags=[TYPE_MAP["news"]],
                timestamp=timestamp,
                url=url,
                mobileUrl=url,
            )
        )
    if not data and timestamp is None:
        raise ValueError("FastBull news feed is empty")
    published = [to_int(node.get("pubTime")) for node in payload["pageDatas"]]
    published = [value for value in published if value]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "raw": payload,
        # +1 keeps the oldest millisecond inclusive against the exclusive bound.
        "next": min(published) + 1 if published else None,
    }


async def backfill_page(
    path_type: str,
    params: dict[str, str],
    cursor: str | None,
    *,
    before: datetime | None = None,
) -> BackfillPage:
    """Flash boards page by ``timestamp`` (releasedDate ms); 头条 by body ``timestamp`` (pubTime ms)."""
    board_type = path_type if path_type in TYPE_MAP else "express"
    if board_type == "en":
        raise ValueError("FastBull en backfill is not supported by the Core parser")
    timestamp = decode_cursor(cursor).get("timestamp")
    if timestamp is None and before is not None:
        timestamp = int(before.timestamp() * 1000)
    if board_type == "news":
        list_data = await _get_news_list(True, timestamp=timestamp)
    else:
        list_data = await _get_feed_list(board_type, True, timestamp=timestamp)
    next_value = list_data["next"]
    return BackfillPage(
        data=_router_data(board_type, list_data).model_copy(update={"fromCache": False}),
        next_cursor=encode_cursor({"timestamp": next_value}) if next_value else None,
        raw_digest=payload_digest(list_data["raw"]),
    )


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.TIME_CURSOR,
        notes="快讯 GET timestamp=上一页 releasedDate 毫秒（含边界）；头条 POST 请求体 timestamp=上一页 pubTime 毫秒。",
        supports_before=True,
        verified_at="2026-10-14",
    ),
    "en": unsupported("英文 API 可翻页，但现有 Core 对非数字 path 整批解析失败；修复解析前不得回溯。"),
}
