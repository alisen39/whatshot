"""人人都是产品经理(woshipm)。

数据源与口径照 board_api 证据 tmp/board_api/woshipm(2026-09-30 冷启动留档,纯 HTTP 直连,
不需要登录、cookie、签名;UA、Referer、Accept 实测均非必需):
- 8 个分类与"最新":原站页面服务端渲染的列表(WordPress)。分类取 /category/<slug> 的
  "最新"页签第 1 页(12 条);"最新"取首页的"最新"页签(20 条,与 /archive 第 1 页逐位相同)。
  页面列表不显示发布时间,timestamp 用同一分类的官方 RSS(/category/<slug>/feed、/feed)
  按链接补,RSS 里没有的条目留空(合作媒体转载不进 RSS,是上游行为不是缺数据)。
  不直接用 RSS 当列表:RSS 不收"合作媒体"转载稿,分类页 12 条里实测 0~8 条、首页 20 条里
  9 条不在 RSS 里,按"与原站页面一致的那个"取页面。
- 日榜 / 周榜 / 月榜:首页"热门"页签组件 hot-post-list 调的
  GET /api2/app/article/popular/{daily|weekly|monthly},页面把 RESULT 全部 100 条显示,
  链接用组件的 permalink https://www.woshipm.com/?p=<id>(301 到正式地址)。
  不存在的类型返回 {"RESULT":{},"CODE":500} 错误壳,按 RESULT 非列表拒绝。
分类页列表上方的两张推荐卡片(category-card)与侧栏"热门文章"不属于列表,不输出。
"""

from __future__ import annotations

import html
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "woshipm"

_BASE = "https://www.woshipm.com"

# 分类子榜 -> 分类 slug(页面 /category/<slug>,同名 RSS /category/<slug>/feed)
_CATEGORIES: dict[str, str] = {
    "it": "it",
    "ucd": "ucd",
    "pd": "pd",
    "operate": "operate",
    "evaluating": "evaluating",
    "chuangye": "chuangye",
    "user-research": "user-research",
    "marketing": "marketing",
}

_POPULAR: dict[str, str] = {"daily": "日榜", "weekly": "周榜", "monthly": "月榜"}

# 声明序第一个是默认榜(latest)
type_map: dict[str, str] = {
    "latest": "最新",
    "it": "业界动态",
    "ucd": "交互体验",
    "pd": "产品设计",
    "operate": "产品运营",
    "evaluating": "分析评测",
    "chuangye": "创业学院",
    "user-research": "用户研究",
    "marketing": "营销推广",
    **_POPULAR,
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "人人都是产品经理",
    "description": "人人都是产品经理：8 个分类的最新文章、首页最新、热门日榜 / 周榜 / 月榜。",
    "link": f"{_BASE}/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = "latest"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}

# 列表所在的 Vue 页签块:分类页"最新"页签是 homeTab == 'latest',
# 首页"最新"页签是 homeTab == 'all'(首页的 latest 是"推荐"页签,反着的)
_TAB_MARKER = {"home": "homeTab == 'all'", "category": "homeTab == 'latest'"}


def _page_url(board: str) -> str:
    return f"{_BASE}/" if board == "latest" else f"{_BASE}/category/{_CATEGORIES[board]}"


def _feed_url(board: str) -> str:
    return f"{_BASE}/feed" if board == "latest" else f"{_BASE}/category/{_CATEGORIES[board]}/feed"


def _tab_block(page: str, marker: str) -> str:
    """取 <template v-if="<marker>"> 与 </template> 之间的 HTML(块内没有嵌套 template)。

    不带 <template> 标签本身:bs4 把 template 里的文字当 TemplateString,
    get_text 取不到,标题、作者、摘要都会变空。
    """
    opening = f'<template v-if="{marker}">'
    start = page.find(opening)
    if start < 0:
        raise RuntimeError(f"woshipm page has no tab block {marker!r} (page changed)")
    end = page.find("</template>", start)
    return page[start + len(opening) : end] if end > 0 else page[start + len(opening) :]


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""


def parse_postlist(block: str) -> list[ListItem]:
    """解析页签块里的 article.postlist-item(按页面顺序,data-id 去重)。"""
    soup = BeautifulSoup(block, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for article in soup.select("article.postlist-item"):
        link = article.select_one("h2.post-title a[href]")
        if link is None:
            continue
        url = str(link.get("href") or "").strip()
        title = _text(link) or str(link.get("title") or "").strip()
        item_id = str(article.get("data-id") or "").strip() or url
        if not url or not title or item_id in seen:
            continue
        seen.add(item_id)
        img = article.select_one(".post-img img[src]")
        cover = str(img.get("src") or "").strip() if img else ""
        items.append(
            ListItem(
                id=item_id,
                title=title,
                url=url,
                mobileUrl=url,
                cover=("https:" + cover) if cover.startswith("//") else cover or None,
                author=_text(article.select_one(".author a.ui-captionStrong")) or None,
                desc=_text(article.select_one(".des")) or None,
            )
        )
    return items


async def _fetch_page_board(board: str, no_cache: bool) -> dict:
    kind = "home" if board == "latest" else "category"
    page_result = await get(
        url=_page_url(board), headers=_HEADERS, no_cache=no_cache, response_type="text"
    )
    items = parse_postlist(_tab_block(page_result.data, _TAB_MARKER[kind]))
    if not items:
        raise RuntimeError(f"woshipm {board} parsed no items from {_page_url(board)}")
    # 页面列表不显示时间:同名 RSS 按链接补发布时间;feed 失效只影响 timestamp 覆盖率,不拒榜
    feed_times: dict[str, int] = {}
    try:
        feed_result = await get(
            url=_feed_url(board), headers=_HEADERS, no_cache=no_cache, response_type="text"
        )
        feed_times = {
            item.url: item.timestamp
            for item in parse_feed(feed_result.data)
            if item.url and item.timestamp
        }
    except Exception:  # noqa: BLE001 - timestamp 是选填,feed 取不到不拒榜
        feed_times = {}
    return {
        "from_cache": page_result.from_cache,
        "update_time": page_result.update_time,
        "data": [item.model_copy(update={"timestamp": feed_times.get(item.url)}) for item in items],
    }


def _popular_item(row: Any) -> ListItem | None:
    data = row.get("data") if isinstance(row, dict) else None
    if not isinstance(data, dict) or not data.get("id") or not data.get("articleTitle"):
        return None
    item_id = str(data["id"])
    # 页面组件 hot-post-list 的 permalink,与 tophub 同形;data.type 有时为空,拼不出栏目路径
    url = f"{_BASE}/?p={item_id}"
    return ListItem(
        id=item_id,
        title=html.unescape(str(data["articleTitle"])).strip(),
        url=url,
        mobileUrl=url,
        hot=row.get("scores"),  # 榜单按 scores 倒序;页面不显示这个数
        cover=data.get("imageUrl") or None,
        author=data.get("articleAuthor") or None,
        desc=html.unescape(str(data.get("articleSummary") or "")).strip() or None,
        timestamp=data.get("publishTime"),  # 毫秒,models 校验器兜底
    )


async def _fetch_popular(board: str, no_cache: bool) -> dict:
    url = f"{_BASE}/api2/app/article/popular/{board}"
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="json")
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("RESULT")
    if not isinstance(rows, list):
        # 不存在的类型(如 yearly)返回 {"RESULT":{},"CODE":500,"MESSAGE":...} 错误壳
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"woshipm popular {board} returned no RESULT list "
            f"code={payload.get('CODE')} message={payload.get('MESSAGE')}"
        )
    items = [item for item in (_popular_item(row) for row in rows) if item is not None]
    if not items:
        raise RuntimeError(f"woshipm popular {board} RESULT has no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", DEFAULT_TYPE)
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    if board in _POPULAR:
        rows = await _fetch_popular(board, no_cache)
    else:
        rows = await _fetch_page_board(board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[board],
        total=len(rows["data"]),
        fromCache=rows["from_cache"],
        updateTime=rows["update_time"],
        data=rows["data"],
    )
