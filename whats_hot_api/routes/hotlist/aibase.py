from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "aibase"

SOURCE_LINK = "https://www.aibase.com/zh/daily"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "AIbase",
    "description": "AIbase 每日 AI 行业趋势精选",
    "link": SOURCE_LINK,
}

_NEWS_PATH_RE = re.compile(r"^/news/(\d+)/?$")
_LEADING_RANK_RE = re.compile(r"^\s*\d+\s*[、,，.．]\s*")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="每日 AI 趋势",
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
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        },
    )
    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for anchor in soup.select(".bg-white .grid a[href]"):
        href = str(anchor.get("href") or "").strip()
        path = urlparse(urljoin(SOURCE_LINK, href)).path
        match = _NEWS_PATH_RE.fullmatch(path)
        if match is None:
            continue
        item_id = match.group(1)
        if item_id in seen_ids:
            continue
        title = _LEADING_RANK_RE.sub("", anchor.get_text(" ", strip=True)).strip()
        if not title:
            continue
        seen_ids.add(item_id)
        item_url = f"https://www.aibase.com/news/{item_id}"
        data.append(
            ListItem(
                id=item_id,
                title=title,
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
