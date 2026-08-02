from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "douban-book"

SOURCE_LINK = "https://book.douban.com/chart"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "豆瓣读书",
    "description": "豆瓣读书当月热门图书榜",
    "link": SOURCE_LINK,
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type=list_data["type"],
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
        headers=_HEADERS,
    )
    soup = BeautifulSoup(result.data, "html.parser")
    heading = soup.select_one("#content h1, h1")
    type_label = _text(heading.get_text(" ", strip=True) if heading else "")
    data = [_book_item(item) for item in soup.select(".media.clearfix")]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "type": type_label or "热门图书榜",
        "data": [item for item in data if item is not None],
    }


def _book_item(item) -> ListItem | None:  # noqa: ANN001
    anchor = item.select_one('h2 a[href*="/subject/"]')
    href = str(anchor.get("href") or "").strip() if anchor else ""
    match = re.search(r"/subject/(\d+)", href)
    title = _text(anchor.get_text(" ", strip=True) if anchor else "")
    if match is None or not title:
        return None

    item_id = match.group(1)
    abstract = _text(_node_text(item.select_one(".subject-abstract")))
    parts = [part.strip() for part in abstract.split("/") if part.strip()]
    author = parts[0] if parts else None
    rating = _float_text(_node_text(item.select_one(".subject-rating .font-small")))
    votes = _number(_node_text(item.select_one(".subject-rating .color-gray")))
    tags = [
        _text(tag.get_text(" ", strip=True))
        for tag in item.select(".subject-tags .tag")
        if _text(tag.get_text(" ", strip=True))
    ]
    rank = _number(_node_text(item.select_one(".green-num-box")))
    description = " · ".join(
        part
        for part in (
            f"排名：{rank}" if rank else None,
            f"评分：{rating}" if rating else None,
            abstract or None,
            " / ".join(tags) or None,
        )
        if part
    )
    cover = item.select_one("img.subject-cover, .media__img img")
    canonical_url = f"https://book.douban.com/subject/{item_id}/"
    return ListItem(
        id=item_id,
        title=title,
        author=author,
        desc=description or None,
        cover=str(cover.get("src") or "").strip() or None if cover else None,
        hot=votes,
        url=href if href.startswith("https://book.douban.com/") else canonical_url,
        mobileUrl=f"https://m.douban.com/book/subject/{item_id}/",
    )


def _node_text(node) -> str:  # noqa: ANN001
    return node.get_text(" ", strip=True) if node else ""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _number(value: object) -> int:
    match = re.search(r"\d+", _text(value))
    return int(match.group(0)) if match else 0


def _float_text(value: object) -> str:
    match = re.search(r"\d+(?:\.\d+)?", _text(value))
    return match.group(0) if match else ""
