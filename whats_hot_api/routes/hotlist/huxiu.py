from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "huxiu"

ROUTE_META: dict = {
    "name": "huxiu",
    "title": "虎嗅",
    "link": "https://www.huxiu.com/moment/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://moment-api.huxiu.com/web-v3/moment/feed?platform=www"
    result = await get(
        url=url,
        no_cache=no_cache,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.huxiu.com/moment/",
        },
    )
    moment_list = (result.data.get("data") or {}).get("moment_list") or {}
    items = moment_list.get("datalist") or []
    data = []
    for v in items:
        content = re.sub(r"<br\s*/?>", "\n", v.get("content", ""), flags=re.IGNORECASE)
        lines = [s.strip() for s in content.split("\n") if s.strip()]
        title_line = lines[0].rstrip("\u3002") if lines else ""
        intro = "\n".join(lines[1:]) if len(lines) > 1 else ""
        moment_id = v.get("object_id", "")
        user_info = v.get("user_info") or {}
        count_info = v.get("count_info") or {}
        data.append(
            ListItem(
                id=moment_id,
                title=title_line,
                desc=intro or None,
                author=user_info.get("username", ""),
                timestamp=get_time(v.get("publish_time")),
                hot=count_info.get("agree_num"),
                url=f"https://www.huxiu.com/moment/{moment_id}.html",
                mobileUrl=f"https://m.huxiu.com/moment/{moment_id}.html",
            )
        )
    return RouterData(
        **ROUTE_META,
        type="24小时",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
