from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import content_status

ROUTE_NAME = "mktnews-flash"
SOURCE_LINK = "https://mktnews.net/"
ROUTE_META = {"name": ROUTE_NAME, "title": "MKTNews · 快讯", "description": "MKTNews 实时财经快讯", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url="https://api.mktnews.net/api/flash", params={"type": "0", "limit": "50"}, no_cache=no_cache, ttl=config.NEWSFLASH_CACHE_TTL, response_type="json", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    rows = sorted((result.data or {}).get("data") or [], key=lambda row: get_time(row.get("time")) or 0, reverse=True)
    data: list[NewsFlashItem] = []
    for row in rows:
        payload = row.get("data") or {}
        content = str(payload.get("content") or "").strip()
        title = str(payload.get("title") or "").strip()
        match = re.match(r"^【([^】]*)】", content)
        title = title or (match.group(1) if match else content)
        item_id = row.get("id")
        if not title or not item_id:
            continue
        url = f"https://mktnews.net/flashDetail.html?id={item_id}"
        data.append(NewsFlashItem(id=item_id, title=title, content=content or title, contentStatus=content_status(content or title, fallback="summary"), source="MKTNews", isImportant=row.get("important") == 1, timestamp=get_time(row.get("time")), url=url, mobileUrl=url))
    return RouterData(kind="newsflash", **ROUTE_META, type="快讯", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
