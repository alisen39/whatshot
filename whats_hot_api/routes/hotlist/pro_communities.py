"""专业社区：小木虫、脉脉（多站点，type=站点-栏目）。

迁移自 board_api pro_communities 单元，每个子榜 1 个请求（即刻 2 个圈子 2026-11-12 移到快讯路由 ``jike``）：
- 小木虫（muchong.com，GBK）6 个榜：帖子排行榜页 ``top-<榜>-1``（服务端渲染 HTML，``tr.forum_list``），
  榜：dayhot 24小时热榜、yule 休闲娱乐、scredit 散金热榜、digest 最新精华贴、helpcredit 热门悬赏贴、
  hot 热门话题贴。末尾 ``-1`` 是页码，只取第 1 页（最新精华贴共 3 页、热门悬赏贴共 2 页）。
  「回复/查看」列的查看数恒为回复数 × 50（board_api 6 榜实测），不是真实浏览量，hot 取回复数；
  timestamp 取发帖日期（页面只到日，北京时间当天 0 点）。「最新精华贴」按设精时间排，条目发帖日期可能很旧
- 脉脉（maimai.cn）热榜：热榜页 ``/n/content/hot-rank/topic`` 是 Next.js 服务端渲染，
  取 ``__NEXT_DATA__.props.pageProps.topics``；话题链接 ``global-topic?circle_type=<type 或 9>&topic_id=<id>``；
  数据里没有时间，timestamp 留空

丁香园论坛热榜要过极验 GEETEST v4 人机验证（PC 页与帖子页都是验证页，H5 包里没有热榜接口），不迁（board_api README）。
请求头照 board_api 证据：小木虫、脉脉用 python-httpx 缺省请求头也 200、数据相同，路由照 whatshot 惯例带项目缺省 Chrome UA。
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "pro-communities"

_TYPE_MAP: dict[str, str] = {
    "muchong-dayhot": "小木虫 · 24小时热榜",
    "muchong-yule": "小木虫 · 休闲娱乐榜",
    "muchong-scredit": "小木虫 · 散金热榜",
    "muchong-digest": "小木虫 · 最新精华贴",
    "muchong-helpcredit": "小木虫 · 热门悬赏贴",
    "muchong-hot": "小木虫 · 热门话题贴",
    "maimai-hot": "脉脉 · 热榜",
}

_DEFAULT_TYPE = "muchong-dayhot"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "专业社区",
    "description": "小木虫帖子排行榜（24小时热榜、休闲娱乐、散金热榜、最新精华贴、热门悬赏贴、热门话题贴）、脉脉热榜。",
    "link": "https://muchong.com/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# 小木虫子榜 -> (排行榜 URL 里的榜名, 页面上的榜名)
_MUCHONG: dict[str, tuple[str, str]] = {
    "muchong-dayhot": ("dayhot", "24小时热榜"),
    "muchong-yule": ("yule", "休闲娱乐"),
    "muchong-scredit": ("scredit", "散金热榜"),
    "muchong-digest": ("digest", "最新精华贴"),
    "muchong-helpcredit": ("helpcredit", "热门悬赏贴"),
    "muchong-hot": ("hot", "热门话题贴"),
}

_MAIMAI = "https://maimai.cn/n/content/hot-rank/topic"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    if board in _MUCHONG:
        list_data = await _get_muchong(board, no_cache)
    else:
        list_data = await _get_maimai(no_cache)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


def _finish(result: RequestResult, items: list[ListItem]) -> dict:
    if not items:
        raise RuntimeError(f"{ROUTE_NAME} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": None,
    }


def _gbk_text(result: RequestResult) -> str:
    """小木虫页面按 GB18030（超集）解码，不依赖响应头 charset。"""
    return result.data.decode("gb18030", "replace") if isinstance(result.data, bytes) else str(result.data)


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _next_data_props(html: str) -> dict[str, Any]:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        raise RuntimeError("page has no __NEXT_DATA__ (page changed)")
    data = json.loads(match.group(1))
    props = (data.get("props") or {}).get("pageProps") if isinstance(data, dict) else None
    if not isinstance(props, dict):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "__NEXT_DATA__ has no props.pageProps (page changed)"
        )
    return props


# ---------------------------------------------------------------- 小木虫


async def _get_muchong(board: str, no_cache: bool) -> dict:
    name, label = _MUCHONG[board]
    url = f"https://muchong.com/top-{name}-1"
    result = await get(
        url=url,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="arraybuffer",  # 字节流自己按 GBK 解码
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    html = _gbk_text(result)
    if label not in html:
        # 排行榜 URL 对不存在的榜会渲染出别的页；照 board_api 用页面榜名做存在性校验
        raise RuntimeError(f"muchong page {url} does not contain board title '{label}' (page changed)")
    items = _muchong_items(BeautifulSoup(html, "lxml"))
    return _finish(result, items)


def _muchong_items(soup: BeautifulSoup) -> list[ListItem]:
    """排行榜表格 tr.forum_list：[版块] 标题 / 作者 + 发帖日期 / 回复/查看 / 最后回复。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for tr in soup.select("tr.forum_list"):
        th = tr.select_one("th")
        if th is None:
            continue
        # 标题链接是 /t-<tid>-1；同一格里还有长帖的分页链接（/t-<tid>-2 …，文字是页码），跳过；
        # 页脚「清除COOKIES」链到 t-11622561-1，也不算条目
        anchor = next(
            (a for a in th.select("a[href]") if re.search(r"/t-\d+-1$", str(a.get("href") or "")) and not _text(a).isdigit()),
            None,
        )
        match = re.search(r"/t-(\d+)-1$", str(anchor.get("href") or "")) if anchor is not None else None
        title = _text(anchor) if anchor is not None else ""
        if match is None or not title or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        by = tr.select_one("td.by")
        num = _text(tr.select_one("td.num"))  # "回复/查看"，查看数恒为回复数 × 50，不是实际浏览量
        replies = re.match(r"(\d+)\s*/", num)
        url = f"https://muchong.com/t-{match.group(1)}-1"
        items.append(
            ListItem(
                id=match.group(1),
                title=title,
                url=url,
                mobileUrl=url,
                hot=int(replies.group(1)) if replies else None,
                author=(_text(by.select_one("cite")) or None) if by else None,
                desc=_text(th.select_one("span a")) or None,
                # 发帖日期只到日，北京时间当天 0 点；get_time 对 "2026-9-26"/"2026-09-26" 都按北京时间 0 点换算
                timestamp=get_time(_text(by.select_one("span"))) if by else None,
            )
        )
    return items


# ---------------------------------------------------------------- 脉脉


async def _get_maimai(no_cache: bool) -> dict:
    result = await get(
        url=_MAIMAI,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:maimai-hot",
    )
    props = _next_data_props(str(result.data))
    topics = props.get("topics")
    if not isinstance(topics, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "maimai hot-rank page has no topics list (page changed)"
        )
    items: list[ListItem] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        topic_id = str(topic.get("id") or "")
        name = str(topic.get("name") or "").strip()
        if not topic_id or not name:
            continue
        url = f"https://maimai.cn/n/content/global-topic?circle_type={topic.get('type') or 9}&topic_id={topic_id}"
        card = topic.get("hot_type_card")
        card_text = str(card.get("text") or "").strip() if isinstance(card, dict) else ""
        items.append(
            ListItem(
                id=topic_id,
                title=name,
                url=url,
                mobileUrl=url,
                hot=topic.get("view_count"),
                cover=topic.get("icon") or None,
                # 角标文字（如「热议」），没有为空；数据里没有时间，timestamp 留空
                desc=card_text or None,
                badges=[{"text": card_text}] if card_text else [],
            )
        )
    return _finish(result, items)
