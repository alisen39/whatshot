from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import content_status

ROUTE_NAME = "fastbull"

SOURCE_LINK = "https://www.fastbull.com/"
TYPE_MAP = {"express": "快讯", "news": "头条"}
_PATHS = {"express": "/cn/express-news", "news": "/cn/news"}
_HEADERS = {
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
    list_data = await _get_list(board_type, no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    result = await get(
        url=urljoin(SOURCE_LINK, _PATHS[board_type]),
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={**_HEADERS, "Referer": SOURCE_LINK},
    )
    soup = BeautifulSoup(result.data, "lxml")
    data: list[NewsFlashItem] = []
    for node in soup.select(".news-list, .trending_type"):
        link = node.select_one(".title_name, .title")
        href = (link.get("href") if link else None) or node.get("href")
        title = _text(link.get_text(" ", strip=True) if link else "")
        if title.startswith("【") and "】" in title:
            title = title.split("】", 1)[0][1:].strip()
        url = urljoin(SOURCE_LINK, href or "")
        if not title or not url.startswith(("http://", "https://")):
            continue
        date_node = node.select_one("[data-date]")
        timestamp = get_time(node.get("data-date") or (date_node.get("data-date") if date_node else None))
        summary_node = node.select_one(".content, .desc, .summary")
        summary = _text(summary_node.get_text(" ", strip=True) if summary_node else "")
        content = summary or title
        data.append(
            NewsFlashItem(
                id=href or url,
                title=title,
                content=content,
                summary=summary or None,
                contentStatus=content_status(content, fallback="summary"),
                source="法布财经",
                tags=[TYPE_MAP[board_type]],
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
