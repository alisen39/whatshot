from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "36kr-quick"

SOURCE_LINK = "https://www.36kr.com/newsflashes"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "36氪快讯",
    "description": "36氪 24 小时快讯",
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
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    soup = BeautifulSoup(result.data, "lxml")
    data: list[NewsFlashItem] = []
    for element in soup.select(".newsflash-item"):
        anchor = element.select_one("a.item-title")
        if anchor is None:
            continue
        title = anchor.get_text(" ", strip=True)
        href = str(anchor.get("href") or "").strip()
        if not title or not href:
            continue
        item_url = urljoin("https://www.36kr.com", href)
        time_element = element.select_one(".time")
        data.append(
            NewsFlashItem(
                id=href,
                title=title,
                content=title,
                contentStatus="summary",
                source="36氪",
                timestamp=get_time(
                    time_element.get_text(" ", strip=True) if time_element else None
                ),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
