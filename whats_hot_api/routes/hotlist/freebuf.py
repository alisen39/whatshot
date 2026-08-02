from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "freebuf"
SOURCE_LINK = "https://www.freebuf.com/"
ROUTE_META = {"name": ROUTE_NAME, "title": "Freebuf · 网络安全", "description": "Freebuf 网络安全资讯", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0", "Referer": SOURCE_LINK})
    data: list[ListItem] = []
    for article in BeautifulSoup(result.data, "lxml").select(".article-item"):
        title_node = article.select_one(".title-left .title")
        anchor = title_node.parent if title_node else None
        href = anchor.get("href") if anchor else None
        title = _text(title_node.get_text(" ", strip=True) if title_node else "")
        url = urljoin(SOURCE_LINK, href or "")
        if not title or not url.startswith("http"):
            continue
        desc_node = article.select_one(".item-right .text-line-2")
        cover_node = article.select_one(".img-view img")
        data.append(ListItem(id=_last_digits(url) or url, title=title, desc=_text(desc_node.get_text(" ", strip=True) if desc_node else "") or None, cover=cover_node.get("src") if cover_node else None, url=url, mobileUrl=url))
    return RouterData(**ROUTE_META, type="网络安全", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)


def _text(value: object) -> str: return " ".join(str(value or "").split())
def _last_digits(value: str) -> str | None:
    match = re.search(r"(\d+)(?!.*\d)", value)
    return match.group(1) if match else None
