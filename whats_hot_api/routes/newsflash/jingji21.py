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
    compact_objects,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "21jingji"

SOURCE_LINK = "https://www.21jingji.com/channel/politics/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "21财经",
    "description": "21财经 24小时快讯",
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
    url = "https://api.21jingji.com/timestream/getListweb"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        params={"page": "1"},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    payload = _decode_payload(result.data)
    items = payload.get("list") or payload.get("data", {}).get("list") or []
    data: list[NewsFlashItem] = []
    for it in items:
        title = text_or_none(it.get("title") or it.get("shortTitle"))
        content = strip_html(
            it.get("content")
            or it.get("timestream")
            or it.get("description")
            or title
        )
        if not title and not content:
            continue

        detail_url = (
            text_or_none(it.get("url"))
            or text_or_none(it.get("linkurl"))
            or SOURCE_LINK
        )
        summary = strip_html(it.get("description"))
        source = (
            text_or_none(it.get("source"))
            or text_or_none(it.get("author"))
            or text_or_none(it.get("username"))
            or "21财经"
        )

        data.append(
            NewsFlashItem(
                id=str(it.get("id") or f"21jingji-{len(data)}"),
                title=title or content[:60],
                content=content,
                summary=summary if summary and summary != content else None,
                contentStatus=content_status(content),
                source=source,
                isImportant=(
                    truthy_flag(it.get("important"))
                    or truthy_flag(it.get("redMark"))
                    or truthy_flag(it.get("top"))
                    or truthy_flag(it.get("warning"))
                ),
                tags=_split_tags(it.get("keywords")) + _split_tags(it.get("tag")),
                images=[
                    *compact_urls(it.get("thumb")),
                    *compact_urls(it.get("video_thumb")),
                ],
                symbols=(
                    compact_objects(it.get("stock_data"))
                    + compact_objects(it.get("stock"))
                    + compact_objects(it.get("stocks"))
                ),
                metrics=metrics(
                    riskRating=to_int(it.get("riskrating")),
                    productId=to_int(it.get("21ProductID")),
                    status=to_int(it.get("status")),
                    audit=to_int(it.get("audit")),
                ),
                timestamp=get_time(it.get("inputtime") or it.get("updatetime")),
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
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _split_tags(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,，;；\s]+", str(value))

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
