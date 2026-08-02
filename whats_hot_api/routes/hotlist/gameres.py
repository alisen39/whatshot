from __future__ import annotations

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "gameres"

ROUTE_META: dict = {
    "name": "gameres",
    "title": "GameRes 游资网",
    "description": "面向游戏从业者的游戏开发资讯，旨在为游戏制作人提供游戏研发类的程序技术、策划设计、艺术设计、原创设计等资讯内容。",
    "link": "https://www.gameres.com",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.gameres.com"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    soup = BeautifulSoup(result.data, "html.parser")
    container = soup.select_one('div[data-news-pane-id="100000"]')
    articles = container.select("article.feed-item") if container else []
    data = []
    for idx, el in enumerate(articles):
        title_el = el.select_one(".feed-item-title-a")
        title = title_el.get_text(strip=True) if title_el else ""
        href = title_el.get("href", "") if title_el else ""
        item_url = href if href.startswith("http") else f"https://www.gameres.com{href}"
        img_tag = el.select_one(".thumb")
        cover = img_tag.get("data-original", "") if img_tag else ""
        desc_el = el.select_one(".feed-item-right > p")
        desc = desc_el.get_text(strip=True) if desc_el else None
        mark_info = el.select_one(".mark-info")
        date_time = ""
        if mark_info and mark_info.contents:
            first = mark_info.contents[0]
            date_time = first.strip() if isinstance(first, str) else first.get_text(strip=True)
        timestamp = get_time(date_time) if date_time else None
        data.append(
            ListItem(
                id=item_url.rstrip("/").split("/")[-1] if item_url else str(idx),
                title=title,
                desc=desc,
                cover=cover or None,
                timestamp=timestamp,
                hot=None,
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return RouterData(
        **ROUTE_META,
        type="最新资讯",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
