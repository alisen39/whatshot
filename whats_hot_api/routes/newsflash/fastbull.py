from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import content_status, to_int

ROUTE_NAME = "fastbull"

SOURCE_LINK = "https://www.fastbull.com/"
# The express feed is the fastbull-news-service JSON gateway behind the FastBull
# apps and the .cn homepage ticker. The api.fastbull.cn host serves the zh
# edition; api.fastbull.com would serve en. The legacy .com SSR page now 302s
# CN clients to the .cn trading site, so the JSON feed is the geo-independent
# source of truth for flash boards.
FEED_URL = "https://api.fastbull.cn/fastbull-news-service/api/getNewsPageByTagIds"
FEED_PAGE_SIZE = 50
FLASH_ID_PREFIX = "/cn/fastshort/"
TYPE_MAP = {
    "express": "快讯",
    "important": "重要快讯",
    "news": "头条",
}
# The 头条 board has no JSON equivalent; it stays on the legacy SSR page.
_PATHS = {"news": "/cn/news"}
_NATIVE_ID_RE = re.compile(r"\d+(?:_\d+)*")
FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.fastbull.cn/",
}
SSR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_feed_list(board_type: str, no_cache: bool) -> dict:
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "pageSize": str(FEED_PAGE_SIZE),
            "checkImportant": "1" if board_type == "important" else "0",
        },
        headers=FEED_HEADERS,
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
        raise ValueError("FastBull feed is missing its pageDatas list")
    data: list[NewsFlashItem] = []
    seen: set[str] = set()
    for node in payload["pageDatas"]:
        if not isinstance(node, dict):
            raise ValueError("FastBull feed row is not an object")
        native_id = str(node.get("path") or "")
        if not _NATIVE_ID_RE.fullmatch(native_id):
            raise ValueError("FastBull flash is missing its native id")
        item_id = FLASH_ID_PREFIX + native_id
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
    if not data and board_type == "express":
        raise ValueError("FastBull express feed is empty")
    # The important board filters to important==1 flashes, so an empty page is
    # a legitimate quiet-window state there.
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_news_list(no_cache: bool) -> dict:
    result = await get(
        url=urljoin(SOURCE_LINK, _PATHS["news"]),
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={**SSR_HEADERS, "Referer": SOURCE_LINK},
    )
    soup = BeautifulSoup(result.data, "lxml")
    data: list[NewsFlashItem] = []
    nodes = soup.select(".news_main .trending_type, #report_list-main .trending_type")
    if not nodes:
        raise ValueError("FastBull news main list is missing or empty")
    seen: set[str] = set()
    for node in nodes:
        link = node.select_one(".title_name, .title")
        title = _text(link.get_text(" ", strip=True) if link else "")
        if not title:
            continue
        href = str(node.get("href") or "")
        match = re.fullmatch(r"/cn/news-?detail/(\d+(?:_\d+)*)/?", urlsplit(href).path)
        if not match:
            raise ValueError("FastBull article is missing its detail link")
        # Both spelling variants identify the same article. Keep legacy IDs.
        item_id = f"/cn/news-detail/{match.group(1)}"
        url = urljoin(SOURCE_LINK, href)
        if urlsplit(url).scheme not in {"http", "https"} or urlsplit(url).hostname != "www.fastbull.com":
            raise ValueError("FastBull item has an unexpected detail host")
        if item_id in seen:
            continue
        seen.add(item_id)
        date_node = node.select_one("[data-date]")
        timestamp = get_time(node.get("data-date") or (date_node.get("data-date") if date_node else None))
        summary_node = node.select_one(".content, .desc, .summary, .brief, .tips")
        summary = _text(summary_node.get_text(" ", strip=True) if summary_node else "")
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
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _text(value: object) -> str:
    return " ".join(str(value or "").split())
