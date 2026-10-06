"""IT 之家与快科技（多站点，type=站点-栏目）。

迁移自 board_api ithome_mydrivers 单元（12 个已完成榜），每个子榜 1 个请求，
全部是原站服务端直出的页面或官方 RSS，无签名、无 cookie（UA 不限，board_api verify/header_matrix.md）：
- IT 之家排行 ``m.ithome.com/rankm/``：一页 4 个榜（日 / 周 / 热评 / 月），每个是
  ``div.rank-name[data-rank-type]`` 后面紧跟的 ``div.rank-box``，按 data-rank-type 单取
  （week-rank、hot-comment-rank、month-rank）。whatshot 既有 ithome 路由把 4 个 tab 拼成一个
  48 条的列表没法单取；日榜 ``ithome-ranking-24h`` 已支持，不在本路由。
  页面只显示「06:09」「昨日 23:15」「09月27日」这类相对时间，且 CDN 不一定遵守
  ``s-maxage=600``（board_api 推翻性验证拿到过比请求早 10 小时 44 分钟生成的页面），
  相对时间以响应 ``Date`` 头（页面生成时刻）为基准换算，不用本机当前时间
- IT 之家频道页：AI=next.ithome.com（智能时代）、IT 资讯=it.ithome.com、智能汽车=auto.ithome.com，
  取主列表 ``#list ul.bl > li``（页面首屏，「加载更多」之前），时间取 ``div.c[data-ot]``
- Office 之家热榜：office.ithome.com 侧栏用 ``$("#rank").load("//www.ithome.com/block/rank.html?d=office")``
  载入 4 个 tab，按 tab 名「Office热榜」找 ul（缺省 ``ul#d-4``）。tophub 该榜实际抓的是频道主列表
  （时间序），与榜名不符；按"内容与榜名不符时按榜名取原站列表"取原站的 Office热榜
  解析直接报 ValueError；本路由的 ``ithome_id()`` 两种形态都认。发布时间取内联
  ``jsDateDiff('YYYY/M/D HH:MM:SS')``（北京时间），作者取 ``.editor``（「·」前）
- 最新更新：官方 RSS ``www.ithome.com/rss/``（首页 <link rel=alternate> 声明，60 条），
  与首页「最新」tab 去掉辣品广告后顺序一致
- 快科技：``www.mydrivers.com`` 首页「24小时最热 / 本周最热 / 本月最热」三个 tab 同时直出
  ``ul#newlist_3_1/2/3``（tab 与 ul 的对应已从 index1213.js 的 newstabrankcurrent_test 源码确认）；
  响应头不带 charset，页面 meta 声明 utf-8。条目页面不显示时间，timestamp 留空
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "ithome-mydrivers"

_TYPE_MAP: dict[str, str] = {
    "ithome-latest": "IT之家 · 最新更新",
    "ithome-week": "IT之家 · 周榜",
    "ithome-hot-comment": "IT之家 · 7天热评",
    "ithome-month": "IT之家 · 月榜",
    "ithome-ai": "IT之家 · AI",
    "ithome-it": "IT之家 · IT 资讯",
    "ithome-auto": "IT之家 · 智能汽车",
    "ithome-office-hot": "IT之家 · Office 之家热榜",
    "mydrivers-24h": "快科技 · 24小时最热",
    "mydrivers-week": "快科技 · 本周最热",
    "mydrivers-month": "快科技 · 本月最热",
}

_DEFAULT_TYPE = "ithome-latest"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "IT之家与快科技",
    "description": "IT之家排行（周榜、热评、月榜）、频道列表、Office热榜、喜加一、最新更新；快科技 24 小时 / 本周 / 本月最热。",
    "link": "https://www.ithome.com/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_CHINA_TZ = timezone(timedelta(hours=8))
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_FEED_ACCEPT = "application/rss+xml,application/xml,text/xml"
_BASE_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

RANKM = "https://m.ithome.com/rankm/"
RANK_BOARDS = {"ithome-week": "week-rank", "ithome-hot-comment": "hot-comment-rank", "ithome-month": "month-rank"}
CHANNELS = {
    "ithome-ai": "https://next.ithome.com/",
    "ithome-it": "https://it.ithome.com/",
    "ithome-auto": "https://auto.ithome.com/",
}
OFFICE_RANK = "https://www.ithome.com/block/rank.html?d=office"
ITHOME_RSS = "https://www.ithome.com/rss/"
MYDRIVERS = "https://www.mydrivers.com/"
MYDRIVERS_TABS = {
    "mydrivers-24h": ("newlist_3_1", "24小时最热"),
    "mydrivers-week": ("newlist_3_2", "本周最热"),
    "mydrivers-month": ("newlist_3_3", "本月最热"),
}


# ---------------------------------------------------------------- 通用


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _digits(text: str) -> int | None:
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None


def ithome_id(url: str) -> str | None:
    """文章 id：www.ithome.com/<百万位>/<千位三位>/<三位>.htm 或 m.ithome.com/html/<id>.htm。

    需修点：id 过百万后链接是 /1/xxx/xxx.htm（id = 百万位 + 千位三位 + 个位三位），
    whatshot 既有 ithome-xijiayi 的正则只认 /0/，匹配不上时原样返回 URL 再 int() 报 ValueError。
    """
    match = re.search(r"ithome\.com/(\d+)/(\d{3})/(\d{3})\.htm", url)
    if match:
        return str(int(match.group(1) + match.group(2) + match.group(3)))
    match = re.search(r"/html/(?:[a-z]+/)?(\d+)\.htm", url)
    return match.group(1) if match else None


def ithome_pc_url(news_id: str) -> str:
    number = int(news_id)
    return f"https://www.ithome.com/{number // 1_000_000}/{number // 1000 % 1000:03d}/{number % 1000:03d}.htm"


def ithome_m_url(news_id: str) -> str:
    return f"https://m.ithome.com/html/{news_id}.htm"


def _page_now(headers: dict[str, Any]) -> datetime:
    """页面生成时刻：CDN 缓存副本的相对时间相对的是源站生成时刻——一种带着源站 Date 头
    （rankm 实测拿到过 10 小时前生成的页面），另一种 Date 是发出时刻、另加 Age 头，取 Date 减 Age；
    没有 Date 头或解析不了时用当前北京时间。"""
    raw = next((value for key, value in headers.items() if str(key).lower() == "date"), None)
    try:
        base = parsedate_to_datetime(str(raw)).astimezone(_CHINA_TZ)
    except (TypeError, ValueError):
        return datetime.now(_CHINA_TZ)
    try:
        age = int(str(next((value for key, value in headers.items() if str(key).lower() == "age"), 0) or 0))
    except ValueError:
        age = 0
    return base - timedelta(seconds=max(age, 0))


def rankm_time(text: str, now: datetime) -> int | None:
    """rankm 显示时间 → Unix 秒：「06:09」（今天）、「昨日 23:15」「前天 08:00」、「09月27日」（取 0 点）。

    「今天 / 昨日 / 前天」相对的是页面生成时刻 now（响应 Date 头），不是本机当前时间；
    比基准晚 10 分钟以上视为跨零点（「23:58」其实是昨天）作保险。
    """
    text = (text or "").strip()
    match = re.fullmatch(r"(?:(昨日|昨天|前天)\s*)?(\d{1,2}):(\d{2})", text)
    if match:
        days = {"昨日": 1, "昨天": 1, "前天": 2}.get(match.group(1) or "", 0)
        moment = (now - timedelta(days=days)).replace(
            hour=int(match.group(2)), minute=int(match.group(3)), second=0, microsecond=0
        )
        if moment > now + timedelta(minutes=10):
            moment -= timedelta(days=1)
        return int(moment.timestamp())
    match = re.fullmatch(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", text)
    if match:
        year = int(match.group(1)) if match.group(1) else now.year
        moment = datetime(year, int(match.group(2)), int(match.group(3)), tzinfo=_CHINA_TZ)
        if not match.group(1) and moment > now + timedelta(days=1):  # 跨年
            moment = moment.replace(year=year - 1)
        return int(moment.timestamp())
    return None


def _iso_time(value: str | None) -> int | None:
    """data-ot：2026-09-30T21:24:53.6630000+08:00（小数 7 位，显式截到秒）。"""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", value or "")
    if not match:
        return None
    moment = datetime(*map(int, match.groups()), tzinfo=_CHINA_TZ)
    return int(moment.timestamp())


# ---------------------------------------------------------------- IT 之家


def parse_rankm(page: str, rank_type: str, now: datetime) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    name = soup.select_one(f'div.rank-name[data-rank-type="{rank_type}"]')
    box = name.find_next_sibling("div", class_="rank-box") if name else None
    if not isinstance(box, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"rankm page has no rank-box for data-rank-type={rank_type} (page changed)"
        )
    items: list[ListItem] = []
    for node in box.select(".placeholder"):
        anchor = node.select_one("a[href]")
        news_id = node.get("data-news-id") or (ithome_id(str(anchor["href"])) if anchor else None)
        title = _text(node.select_one(".plc-title"))
        if not news_id or not title:
            continue
        img = node.select_one("img")
        cover = (img.get("data-original") or img.get("src")) if img else None
        items.append(
            ListItem(
                id=str(news_id),
                title=title,
                url=ithome_pc_url(str(news_id)),
                mobileUrl=ithome_m_url(str(news_id)),
                hot=_digits(_text(node.select_one(".review-num"))),  # 「670评」评论数
                cover=str(cover) if cover else None,
                timestamp=get_time(rankm_time(_text(node.select_one("span.post-time")), now)),
            )
        )
    return items


def parse_channel(page: str) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    listing = soup.select_one("#list ul.bl") or soup.select_one("ul.bl")
    if not isinstance(listing, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            "channel page has no ul.bl main list (page changed)"
        )
    items: list[ListItem] = []
    for li in listing.select(":scope > li"):
        anchor = li.select_one("a.title") or li.select_one("h2 a")
        href = str(anchor.get("href") or "") if anchor else ""
        news_id = ithome_id(href)
        if not anchor or not news_id:
            continue
        img = li.select_one("img")
        cover = (img.get("data-original") or img.get("src")) if img else None
        meta = li.select_one("div.c")
        items.append(
            ListItem(
                id=news_id,
                title=str(anchor.get("title") or "") or _text(anchor),
                url=href,
                mobileUrl=ithome_m_url(news_id),
                cover=str(cover) if cover else None,
                desc=_text(li.select_one("div.m")) or None,
                timestamp=get_time(_iso_time(str(meta.get("data-ot") or "")) if meta else None),
            )
        )
    return items


def parse_office_rank(page: str) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    tab = next((li for li in soup.select("ul.bar li") if _text(li) == "Office热榜"), None)
    listing = soup.select_one(f"ul#d-{tab.get('data-id')}") if tab else None
    if not isinstance(listing, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            "rank.html?d=office has no Office热榜 tab (page changed)"
        )
    items: list[ListItem] = []
    for anchor in listing.select("li a[href]"):
        href = str(anchor["href"])
        news_id = ithome_id(href)
        if news_id:
            items.append(
                ListItem(
                    id=news_id,
                    title=str(anchor.get("title") or "") or _text(anchor),
                    url=href,
                    mobileUrl=ithome_m_url(news_id),
                )
            )
    return items




async def _get_ithome_rss(no_cache: bool) -> dict:
    result = await get(
        url=ITHOME_RSS,
        headers={**_BASE_HEADERS, "Accept": _FEED_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:ithome-latest",
    )
    items: list[ListItem] = []
    for entry in parse_feed(str(result.data)):
        news_id = ithome_id(entry.url)
        if not news_id:
            continue
        items.append(entry.model_copy(update={"id": news_id, "mobileUrl": ithome_m_url(news_id)}))
    if not items:
        raise RuntimeError("ithome RSS returned no items with a parsable article id")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


# ---------------------------------------------------------------- 快科技


def parse_mydrivers(page: str, ul_id: str) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    listing = soup.select_one(f"ul#{ul_id}")
    if not isinstance(listing, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"mydrivers home page has no ul#{ul_id} (page changed)"
        )
    items: list[ListItem] = []
    for li in listing.select(":scope > li"):
        anchor = li.select_one("h5 a[href]")
        if not anchor:
            continue
        href = str(anchor["href"])
        match = re.search(r"/(\d+)\.htm", href)
        img = li.select_one("img")
        cover = (img.get("data-original") or img.get("src")) if img else None
        if isinstance(cover, str) and cover.startswith("//"):
            cover = f"https:{cover}"
        items.append(
            ListItem(
                id=match.group(1) if match else href,
                title=_text(anchor),
                url=href,
                mobileUrl=f"https://m.mydrivers.com/newsview/{match.group(1)}.html" if match else href,
                cover=str(cover) if cover else None,
                desc=_text(li.select_one(".phhot_lb_right p")) or None,
                hot=_digits(_text(li.select_one(".readnumber"))),  # 「15774人阅读」
            )
        )
    return items


# ---------------------------------------------------------------- 入口


async def _fetch_page(url: str, board: str, no_cache: bool, accept: str = _HTML_ACCEPT) -> tuple[str, dict[str, Any], RequestResult]:
    """GET 文本页；origin_info 带回响应头（rankm 相对时间换算需要 Date / Age）。"""
    result = await get(
        url=url,
        headers={**_BASE_HEADERS, "Accept": accept},
        no_cache=no_cache,
        response_type="text",
        origin_info=True,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    wrapped = result.data if isinstance(result.data, dict) and isinstance(result.data.get("headers"), dict) else {}
    page = wrapped.get("data")
    if not isinstance(page, str):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"{url} returned non-text response (page changed)"
        )
    return page, wrapped.get("headers") or {}, result


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    from_cache, update_time = False, ""
    if board in RANK_BOARDS:
        page, headers, result = await _fetch_page(RANKM, board, no_cache)
        items = parse_rankm(page, RANK_BOARDS[board], _page_now(headers))
        from_cache, update_time = result.from_cache, result.update_time
    elif board in CHANNELS:
        page, _, result = await _fetch_page(CHANNELS[board], board, no_cache)
        items = parse_channel(page)
        from_cache, update_time = result.from_cache, result.update_time
    elif board == "ithome-office-hot":
        page, _, result = await _fetch_page(OFFICE_RANK, board, no_cache)
        items = parse_office_rank(page)
        from_cache, update_time = result.from_cache, result.update_time
    elif board == "ithome-latest":
        list_data = await _get_ithome_rss(no_cache)
        items = list_data["data"]
        from_cache, update_time = list_data["from_cache"], list_data["update_time"]
    else:
        page, _, result = await _fetch_page(MYDRIVERS, board, no_cache)
        items = parse_mydrivers(page, MYDRIVERS_TABS[board][0])
        from_cache, update_time = result.from_cache, result.update_time
    if not items:
        raise RuntimeError(f"{ROUTE_NAME} board '{board}' returned no items")
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(items),
        fromCache=from_cache,
        updateTime=update_time,
        data=items,
    )
