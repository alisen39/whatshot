from __future__ import annotations

import json
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ifeng"
SOURCE_LINK = "https://www.ifeng.com/"
ROUTE_META = {"name": ROUTE_NAME, "title": "凤凰网 · 热点资讯", "description": "凤凰网热点资讯", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0"})
    match = re.search(r"var\s+allData\s*=\s*(\{[\s\S]*?\});", result.data)
    rows = (json.loads(match.group(1)).get("hotNews1") or []) if match else []
    data = [ListItem(id=row.get("url"), title=row.get("title"), timestamp=get_time(row.get("newsTime")), url=row.get("url"), mobileUrl=row.get("url")) for row in rows if row.get("title") and str(row.get("url") or "").startswith("http")]
    return RouterData(**ROUTE_META, type="热点资讯", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
