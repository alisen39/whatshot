from __future__ import annotations

import json
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "uisdc"

SOURCE_LINK = "https://www.uisdc.com/news"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "优设网",
    "description": "优设 AI 情报与设计行业动态",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="AI 情报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    groups = _embedded_news(result.data or "")
    latest = groups[0] if groups else {}
    group_id = str(latest.get("id") or "latest")
    timestamp = get_time(latest.get("time"))
    data = [
        _news_item(row, group_id, index, timestamp)
        for index, row in enumerate(latest.get("dubao") or [], start=1)
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _embedded_news(html: str) -> list[dict]:
    match = re.search(r'var\s+uisdc_news\s*=\s*"((?:\\.|[^"\\])*)"\s*;', html)
    if not match:
        return []
    try:
        json_text = json.loads(f'"{match.group(1)}"')
        data = json.loads(json_text)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _news_item(
    row: dict, group_id: str, index: int, timestamp: int | None
) -> ListItem | None:
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    content = str(row.get("content") or "").strip()
    marker_url = re.search(r"\[\[(?:官网|全文):([^\]]+)\]\]", content)
    product = row.get("product") if isinstance(row.get("product"), dict) else {}
    url = (
        str(row.get("url") or "").strip()
        or (marker_url.group(1).strip() if marker_url else "")
        or str(product.get("permalink") or "").strip()
        or f"https://www.uisdc.com/?p={group_id}"
    )
    clean_content = re.sub(r"\s*\[\[(?:官网|全文):[^\]]+\]\]\s*", " ", content)
    clean_content = re.sub(r"\s+", " ", clean_content).strip()
    tag = str(row.get("tag") or "").strip()
    desc_parts = [part for part in (tag, clean_content[:220]) if part]
    images = [part.strip() for part in str(row.get("images") or "").split("|") if part.strip()]
    try:
        hot = round(float(row["hot"]) * 10) if row.get("hot") else None
    except (TypeError, ValueError):
        hot = None
    return ListItem(
        id=f"{group_id}-{index}",
        title=title,
        desc=" · ".join(desc_parts) or None,
        hot=hot,
        cover=images[0] if images else None,
        timestamp=timestamp,
        url=url,
        mobileUrl=url,
    )
