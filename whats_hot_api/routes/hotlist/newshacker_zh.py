from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "newshacker-zh"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "News Hacker｜极客洞察",
    "description": "Hacker News 热门帖子的中文标题与讨论摘要（第三方站 newshacker.me，非 HN 官方）",
    "link": "https://newshacker.me/",
}

FEED_URL = "https://api.newshacker.me/rss"

# description 第二段固定是 "<strong>评分:</strong> 24 | <strong>作者:</strong> papergirl";
# 模板改写时取不到就留空,其余字段不受影响
META_RE = re.compile(r"评分:\s*(\d+)\s*\|\s*作者:\s*(\S+)")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        FEED_URL,
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    items = parse_feed(result.data)
    if not items:
        raise RuntimeError("newshacker RSS did not contain any items")
    meta = _score_author(result.data)
    data: list[ListItem] = []
    for item in items:
        found = meta.get(item.id)
        if found:
            item = item.model_copy(update={"hot": found[0], "author": found[1]})
        data.append(item)
    return RouterData(
        **ROUTE_META,
        type="中文精选",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _score_author(xml: str) -> dict[str, tuple[int, str]]:
    """guid -> (HN 分数, 提交者),从每条 description 的"评分 / 作者"段落里取。"""
    out: dict[str, tuple[int, str]] = {}
    for node in BeautifulSoup(xml, "xml").find_all("item"):
        guid, desc = node.find("guid"), node.find("description")
        if not guid or not desc:
            continue
        text = BeautifulSoup(desc.get_text(), "lxml").get_text(" ", strip=True)
        matched = META_RE.search(text)
        if matched:
            out[guid.get_text(strip=True)] = (int(matched.group(1)), matched.group(2))
    return out
