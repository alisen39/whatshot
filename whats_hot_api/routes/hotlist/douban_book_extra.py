"""豆瓣读书扩展榜（douban-book-extra）：最受欢迎的书评（官方 RSS）。

移植自 board_api/douban_book（2026-09-30 已验证，verify/ 下有自验、源 vs 输出核对与推翻性验证）：
- 数据源是豆瓣官方 RSS www.douban.com/feed/review/book（频道"豆瓣最受欢迎的书评"，
  channel link 是 book.douban.com/review/book_best/），20 条，保留 feed 原顺序——
  书评 RSS 不是按时间排的，是"最受欢迎"的名次，不重排
- 路由名加后缀：whatshot 的 douban-book 只有 /chart 热门图书榜，本路由子榜键不同；
  解析方式与 douban-charts 的影评 RSS 同一套（摘要是截断的 Draft.js JSON，封面在 content:encoded）
- 本单元其余 10 个榜（新书速递 9 个、畅销图书榜）列表只在 book.douban.com 上，
  采集机被公司上网策略拦截（TLS 握手重置），记受阻不迁（README"受阻的榜"）

反爬口径（verify/probe.log、douban-charts 同源经验）：
- UA 黑名单：python-httpx 缺省 UA 返回 418，必须带浏览器 UA
- 豆瓣对频率敏感：本路由一次抓取只发 1 个请求，Core 路由缓存天然限频
"""

from __future__ import annotations

import html
import json
import re
from email.utils import parsedate_to_datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "douban-book-extra"

# 声明序第一个（review-best）是默认榜；目前只有这一个子榜
_BOARDS: dict[str, str] = {
    "review-best": "最受欢迎的书评",
}

type_map: dict[str, str] = dict(_BOARDS)

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "豆瓣读书",
    "description": "豆瓣读书：最受欢迎的书评（官方 RSS）",
    "link": "https://book.douban.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_FEED_URL = "https://www.douban.com/feed/review/book"
_FEED_LINK = "https://book.douban.com/review/book_best/"

_HEADERS = {
    # probe.log：python-httpx 缺省 UA 被 418，必须带浏览器 UA
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "review-best")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    result = await get(url=_FEED_URL, headers=_HEADERS, no_cache=no_cache, response_type="text")
    items = _parse_feed(str(result.data))
    if not items:
        raise RuntimeError(f"douban-book-extra {_BOARDS[type_param]} feed has no items (feed changed)")
    return RouterData(
        **{**ROUTE_META, "link": _FEED_LINK},
        type=_BOARDS[type_param],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _join(*parts: object, limit: int = 500) -> str | None:
    text = " · ".join(str(part).strip() for part in parts if part and str(part).strip())
    return text[:limit] or None


def _draft_text(desc: str) -> str:
    """书评摘要是截断的 Draft.js JSON，取其中各段 text 拼起来（照搬 douban-charts）。"""
    texts: list[str] = []
    # 最后一段通常被截断（以 ... 结尾、没有结尾引号），也要取；截断处可能留下半个 \uXXXX 转义，先去掉
    for raw in re.findall(r'"text":\s*"((?:[^"\\]|\\.)*)', desc):
        raw = re.sub(r"\\(u[0-9a-fA-F]{0,3})?$", "", re.sub(r"(\.\.\.|…)$", "", raw))
        try:
            texts.append(json.loads(f'"{raw}"'))
        except ValueError:
            continue
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def _parse_feed(xml: str) -> list[ListItem]:
    """官方 RSS 20 条，保留 feed 原顺序（"最受欢迎"的名次，不按时间重排）。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for node in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):

        def tag(name: str, node: str = node) -> str:
            found = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", node, re.DOTALL)
            return found.group(1).strip() if found else ""

        link, title = tag("link"), _text(tag("title"))
        rid = re.search(r"/review/(\d+)/", link)
        if not rid or not title or rid.group(1) in seen:
            continue
        seen.add(rid.group(1))
        desc = html.unescape(tag("description"))
        # 摘要开头是"<作者>评论: <书名> (<书的链接>)\n评价: <力荐/推荐…>"，去掉链接
        head = re.sub(r"\s*\(https?://[^)]*\)", "", desc.split("{", 1)[0])
        head = re.sub(r"\s+", " ", head).strip()
        cover = re.search(r'<img src="([^"]+)"', tag("content:encoded"))
        try:
            timestamp = get_time(parsedate_to_datetime(tag("pubDate")).timestamp())
        except (TypeError, ValueError, IndexError):
            timestamp = None
        items.append(
            ListItem(
                id=rid.group(1),
                title=title,
                url=link,
                mobileUrl=f"https://m.douban.com/book/review/{rid.group(1)}/",
                author=_text(tag("dc:creator")) or None,
                cover=cover.group(1) if cover else None,
                desc=_join(head, _draft_text(desc)),
                timestamp=timestamp,
            )
        )
    return items
