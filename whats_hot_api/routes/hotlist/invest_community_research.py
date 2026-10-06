"""投资社区与研究报告：雪球、集思录、QuestMobile、Counterpoint（多站点，type=站点-栏目）。

迁移自 board_api invest_community_research 单元（7 个已完成榜；艾瑞咨询 2 个已因上游不可达下线），每个子榜 1~2 个请求：
- 雪球「今日话题」：站内标题为「今日话题」的组件（全部/沪深/美股/港股，"更多"链到 /today）
  请求 ``GET /v4/statuses/public_timeline_by_category.json?since_id=-1&max_id=-1&category=0``
  （「全部」），不带 count 时接口一页 20 条。接口要访客 cookie ``xq_a_token``：先 GET 首页，
  服务器用 Set-Cookie 下发（uid=-1 的访客身份，不是登录），不带返回 400 error_code=400016。
  首页对程序 UA 返回 567，必须带浏览器 UA；文章页有阿里云 WAF JS 挑战，不请求文章页。
  取的是组件那份列表，不是 /today 页缺省的「雪球热帖」tab（后者走 listV2 热帖流，重合 0 条）
- 集思录：「今日热门榜」=讨论区「热门」tab 的「当天」（``sort_type-hot____day-1``，刚过零点
  可能为空，输出 0 条 + message）；「社区最新」=「按发表时间」tab（``category-__sort_type-add_time``）。
  服务端渲染 ``div.aw-question-list``；列表行是"<用户> 发起/回复 • 时间 • N 次浏览"，
  「回复」行的时间与人是最后回复信息（不是发布时间），author/timestamp 留空
- QuestMobile：``GET /api/v2/report/article-list?version=0&pageSize=6&pageNo=1&industryId=-1&labelId=-1``，
  与页面 SSR（QuestMobile-state）同参数同结果，code=100200
- Counterpoint：旧站 china.counterpointresearch.com 已整站 301 到 counterpointresearch.com/cn，
  旧 WordPress RSS 没有了；取新站 /cn/insights 服务端渲染的 12 张卡片（a>article>h3）。
  站点在 Cloudflare 后面：/cn/insights 对浏览器 UA 直接 200，遇挑战页（403/503）报错不绕过

不做：Canalys「数据分析」（已并入 Omdia，newsroom 停在 2025-09-16，见 board_api README）。
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "invest-community-research"

_TYPE_MAP: dict[str, str] = {
    "xueqiu-today": "雪球 · 今日话题",
    "jisilu-hot-today": "集思录 · 今日热门榜（热门 · 当天）",
    "jisilu-latest": "集思录 · 社区最新（按发表时间）",
    "questmobile-reports": "QuestMobile · 行业研究报告",
    "counterpoint-insights": "Counterpoint Research · 最新见解",
}

_DEFAULT_TYPE = "xueqiu-today"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "投资社区与研究报告",
    "description": "雪球今日话题、集思录热门与最新、QuestMobile 行业研究报告、Counterpoint 最新见解。",
    "link": "https://xueqiu.com/today",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_CHINA_TZ = timezone(timedelta(hours=8))
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_JSON_ACCEPT = "application/json, text/plain, */*"
# 雪球首页对 python-httpx 这类程序 UA 返回 567，全部请求按 board_api 证据带浏览器客户端头
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _FETCHERS[board](board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


def _finish(result: Any, items: list[ListItem], message: str | None = None) -> dict:
    if not items and message is None:
        raise RuntimeError(f"{ROUTE_NAME} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": message,
    }


def _beijing_sec(text: str, fmt: str) -> int | None:
    """按北京时间解析上游时间字符串 → 秒；解析不了返回 None（不猜）。"""
    try:
        return int(datetime.strptime(text.strip(), fmt).replace(tzinfo=_CHINA_TZ).timestamp())
    except (TypeError, ValueError, AttributeError):
        return None


def _plain(fragment: str | None) -> str:
    """上游富文本/HTML 片段 → 纯文本（页面组件同样只显示文字）。"""
    text = BeautifulSoup(fragment or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# ---------------------------------------------------------------- 雪球

_XQ_HOME = "https://www.xueqiu.com/"
_XQ_API = "https://www.xueqiu.com/v4/statuses/public_timeline_by_category.json"
# 「今日话题」组件（TodayTopicList）的请求；组件带 count=5 只显示 5 条，不带时接口一页 20 条
_XQ_PARAMS = {"since_id": "-1", "max_id": "-1", "category": "0"}


async def _get_xueqiu(board: str, no_cache: bool) -> dict:
    # 第 1 步 GET 首页：服务器 Set-Cookie 下发 xq_a_token 等访客 cookie（uid=-1，不是登录）。
    # http_client 按域名复用同一个 AsyncClient，cookie 罐自动带到第 2 步；no_cache 强制真发
    await get(
        url=_XQ_HOME,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=True,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}:home",
    )
    result = await get(
        url=_XQ_API,
        params=_XQ_PARAMS,
        headers={
            **_BASE_HEADERS,
            "Accept": _JSON_ACCEPT,
            "Referer": "https://xueqiu.com/today",
            "X-Requested-With": "XMLHttpRequest",
        },
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("list")
    if not isinstance(rows, list):
        # 不带 cookie 时接口返回 400 error_code=400016（get 抛 HTTPStatusError）；
        # 200 但没有 list 也按结构变化处理
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"xueqiu public_timeline_by_category response has no list: {str(payload)[:200]}"
        )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            detail = json.loads(row.get("data") or "{}")
        except ValueError:
            continue
        if not isinstance(detail, dict):
            continue
        target = str(detail.get("target") or "").strip()
        if not target:
            continue
        url = urljoin("https://xueqiu.com/", target)
        # 组件显示 topic_title，没有时显示去掉标签的 description
        title = _plain(detail.get("topic_title") or detail.get("title")) or _plain(detail.get("description"))[:80]
        user = detail.get("user") if isinstance(detail.get("user"), dict) else {}
        cover = detail.get("topic_pic") or detail.get("cover_pic") or detail.get("first_pic")
        created = detail.get("created_at")
        items.append(
            ListItem(
                id=str(detail.get("id") or target),
                title=title,
                url=url,
                hot=detail.get("view_count"),
                author=user.get("screen_name"),
                cover=cover if isinstance(cover, str) and cover.startswith("http") else None,
                desc=_plain(detail.get("description")) or None,
                timestamp=get_time(created) if isinstance(created, (int, float)) and created > 0 else None,
            )
        )
    return _finish(result, items)


# ---------------------------------------------------------------- 集思录

_JSL_PAGES = {
    # 讨论区「热门」tab 里的「当天」（页面链接 sort_type-hot____day-1）
    "jisilu-hot-today": "https://www.jisilu.cn/home/explore/sort_type-hot____day-1",
    # 讨论区「按发表时间」tab
    "jisilu-latest": "https://www.jisilu.cn/home/explore/category-__sort_type-add_time",
}
# 列表行元信息："<用户> 发起/回复 • YYYY-MM-DD HH:MM • N 次浏览"
_JSL_META = re.compile(r"(?P<who>\S+)\s+(?P<act>发起|回复)\s*•\s*(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*•\s*(?P<views>\d+)\s*次浏览")


async def _get_jisilu(board: str, no_cache: bool) -> dict:
    page = _JSL_PAGES[board]
    result = await get(
        url=page,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    soup = BeautifulSoup(str(result.data), "lxml")
    box = soup.select_one("div.aw-question-list")
    if box is None:
        raise RuntimeError(f"jisilu page {page} has no div.aw-question-list (page changed or login wall)")
    items: list[ListItem] = []
    for entry in box.select("div.aw-item"):
        link = entry.select_one("h4 a[href*='/question/']")
        # 标题后可能跟话题标签链接（/topic/…），只取问题链接
        if not isinstance(link, Tag):
            continue
        url = urljoin(page, str(link.get("href")))
        match = re.search(r"/question/(\d+)", url)
        meta = entry.select_one("span.aw-text-color-999")
        info = _JSL_META.search(" ".join(meta.get_text(" ", strip=True).split())) if meta else None
        # 「发起」是楼主与发帖时间；「回复」是最后回复人/时间（不是发布时间，留空）
        posted = bool(info and info.group("act") == "发起")
        items.append(
            ListItem(
                id=match.group(1) if match else url,
                title=link.get_text(" ", strip=True),
                url=url,
                hot=int(info.group("views")) if info else None,
                author=info.group("who") if info and posted else None,
                timestamp=get_time(_beijing_sec(info.group("time"), "%Y-%m-%d %H:%M")) if info and posted else None,
            )
        )
    message = None
    if board == "jisilu-hot-today" and not items:
        # 刚过零点时「当天」热门可能还没有帖子，照原站输出 0 条
        message = "集思录「当天」热门暂时没有帖子（原站此刻为空）"
    return _finish(result, items, message)


# ---------------------------------------------------------------- QuestMobile

_QM_API = "https://www.questmobile.com.cn/api/v2/report/article-list"
_QM_PARAMS = {"version": "0", "pageSize": "6", "pageNo": "1", "industryId": "-1", "labelId": "-1"}


async def _get_questmobile(board: str, no_cache: bool) -> dict:
    result = await get(
        url=_QM_API,
        params=_QM_PARAMS,
        headers={
            **_BASE_HEADERS,
            "Accept": _JSON_ACCEPT,
            "Referer": "https://www.questmobile.com.cn/research/reports/",
        },
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("data")
    if payload.get("code") != 100200 or not isinstance(rows, list):
        raise RuntimeError(f"questmobile article-list returned code={payload.get('code')} (business error)")
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        report_id = str(row.get("id") or "")
        if not report_id:
            continue
        items.append(
            ListItem(
                id=report_id,
                title=str(row.get("title") or "").strip(),
                url=f"https://www.questmobile.com.cn/research/report/{report_id}",
                cover=row.get("coverImgUrl") or None,
                desc=str(row.get("introduction") or "").strip() or None,
                timestamp=get_time(_beijing_sec(str(row.get("publishTime") or ""), "%Y-%m-%d")),
            )
        )
    return _finish(result, items)


# ---------------------------------------------------------------- Counterpoint

_CP_LIST = "https://counterpointresearch.com/cn/insights"


def _cp_image(src: str) -> str | None:
    # Next.js 图片代理 /_next/image?url=<原图>&w=…，取原图地址
    if not src:
        return None
    query = parse_qs(urlsplit(src).query)
    if src.startswith("/_next/image") and query.get("url"):
        return unquote(query["url"][0])
    return urljoin(_CP_LIST, src)


async def _get_counterpoint(board: str, no_cache: bool) -> dict:
    # /cn 首页会返回 Cloudflare 挑战页（403），本路由只请求对缺省 UA 直接 200 的 /cn/insights；
    # 真遇到挑战页时 get 抛 HTTPStatusError 或解析为空报错，不重试、不换 UA 绕过
    result = await get(
        url=_CP_LIST,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    soup = BeautifulSoup(str(result.data), "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href^='/cn/insights/']"):
        card = anchor.select_one("article")
        heading = anchor.select_one("h3")
        # 只取列表卡片（导航、筛选里的链接没有 article/h3）
        if card is None or heading is None:
            continue
        url = urljoin(_CP_LIST, str(anchor.get("href")))
        if url in seen:
            continue
        seen.add(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        date = anchor.select_one("p")
        img = anchor.select_one("img")
        items.append(
            ListItem(
                id=slug,
                title=heading.get_text(" ", strip=True),
                url=url,
                cover=_cp_image(str(img.get("src") or "")) if img else None,
                timestamp=get_time(_beijing_sec(date.get_text(strip=True), "%Y年%m月%d日")) if date else None,
            )
        )
    return _finish(result, items)


_FETCHERS = {
    "xueqiu-today": _get_xueqiu,
    "jisilu-hot-today": _get_jisilu,
    "jisilu-latest": _get_jisilu,
    "questmobile-reports": _get_questmobile,
    "counterpoint-insights": _get_counterpoint,
}
