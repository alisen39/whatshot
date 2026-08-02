from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zaobao"
SOURCE_LINK = "https://www.zaobao.com/realtime/china"
ROUTE_META = {"name": ROUTE_NAME, "title": "联合早报", "description": "联合早报实时新闻", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0"})
    data: list[ListItem] = []
    for link in BeautifulSoup(result.data, "lxml").select("a[href]"):
        title = " ".join(link.get_text(" ", strip=True).split())
        href = link.get("href")
        if len(title) >= 6 and href and "/realtime/" in href:
            url = urljoin("https://www.zaobao.com", href)
            data.append(ListItem(id=href, title=title, url=url, mobileUrl=url))
    return RouterData(**ROUTE_META, type="实时新闻", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
