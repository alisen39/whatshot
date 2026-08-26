from __future__ import annotations

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, NewsFlashItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "techcrunch-robotics"
SOURCE_LINK = "https://techcrunch.com/category/robotics/"
FEED_URL = "https://techcrunch.com/category/robotics/feed/"
TYPE_MAP = {"robotics": "Robotics"}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "TechCrunch · Robotics",
    "description": "Startup and venture coverage focused on robotics.",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": TYPE_MAP,
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "robotics")
    board_type = requested_type if requested_type in TYPE_MAP else "robotics"
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Referer": SOURCE_LINK,
        },
    )
    tags_by_id = _rss_tags_by_id(result.data)
    data = [
        _as_newsflash(item, tags_by_id.get(item.id, []))
        for item in parse_feed(result.data)
    ]
    if not data:
        raise RuntimeError("TechCrunch Robotics feed contained no usable items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _rss_tags_by_id(xml: str) -> dict[str, list[str]]:
    tags_by_id: dict[str, list[str]] = {}
    soup = BeautifulSoup(xml, "xml")
    for node in soup.find_all("item"):
        guid = node.find("guid")
        link = node.find("link")
        item_id = (guid or link).get_text(" ", strip=True) if guid or link else ""
        if not item_id:
            continue
        tags = [tag.get_text(" ", strip=True) for tag in node.find_all("category")]
        tags_by_id[item_id] = list(dict.fromkeys(tag for tag in tags if tag))
    return tags_by_id


def _as_newsflash(item: ListItem, tags: list[str]) -> NewsFlashItem:
    content = item.desc or item.title
    return NewsFlashItem(
        id=item.id,
        title=item.title,
        content=content,
        summary=item.desc,
        contentStatus="summary",
        source=item.author or "TechCrunch",
        tags=tags or ["Robotics"],
        images=[item.cover] if item.cover else [],
        timestamp=item.timestamp,
        url=item.url,
        mobileUrl=item.mobileUrl or item.url,
    )
