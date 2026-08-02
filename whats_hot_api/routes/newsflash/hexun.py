from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
)

ROUTE_NAME = "hexun"

SOURCE_LINK = "https://news.hexun.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "和讯网",
    "description": "和讯网 7x24 小时快讯",
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
    url = "https://opentool.hexun.com/MongodbNewsService/getNewsListByJson.jsp"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        params={
            "id": "189223574",
            "s": "20",
            "cp": "1",
            "callback": "whats_hot_hexun",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Referer": SOURCE_LINK,
        },
    )

    payload = _decode_payload(result.data)
    items = payload.get("result") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title"))
        content = strip_html(it.get("abstract") or title)
        if not title and not content:
            continue

        detail_url = text_or_none(it.get("entityurl")) or SOURCE_LINK
        data.append(
            NewsFlashItem(
                id=str(it.get("id") or f"hexun-{len(data)}"),
                title=title or content[:60],
                content=content,
                summary=content if content and content != title else None,
                contentStatus=content_status(content, fallback="summary"),
                source=text_or_none(it.get("medianame")) or "和讯网",
                tags=_split_tags(it.get("keyword")),
                images=compact_urls(it.get("newsmatchpic")),
                metrics=metrics(
                    mediaId=to_int(it.get("mediaid")),
                    totalPage=to_int(payload.get("totalPage")),
                    totalNumber=to_int(payload.get("totalNumber")),
                ),
                timestamp=get_time(it.get("entitytime")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _decode_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = "" if raw is None else str(raw).strip()
    if not text:
        return {}
    start = text.find("(")
    end = text.rfind(")")
    if start != -1 and end != -1 and end > start:
        text = text[start + 1 : end].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _split_tags(value: object) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,，;；\s]+", str(value)):
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
