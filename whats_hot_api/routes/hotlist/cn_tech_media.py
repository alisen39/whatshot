"""国内科技媒体：爱范儿、极客公园、量子位、雷锋网（多站点，type=站点-栏目）。

迁移自 board_api cn_tech_media 单元（4 个已完成榜；爱范儿 AppSolution 原站已停更不迁，
/app 页最新一篇是 2023-06-15），每个子榜 1 个请求，无签名、无 cookie：
- 爱范儿 每日最新：官方 RSS ``www.ifanr.com/feed``（20 条），与首页「最新」tab 服务端渲染的
  20 篇文章逐位相同（首页插的「大声」「视频」卡片不是文章）；「最新」tab"加载更多"用的
  web-feed 接口第 1 页会把其中一篇换成专栏卡片，不用；RSS 链接带的 utm_* 参数去掉
- 极客公园 七日热门：首页侧栏「七日热门」组件（/dist/app.*.js）请求
  ``mainssl.geekpark.net/api/v1/posts/hot_in_week?per=7``，按返回顺序渲染、列表按 views 倒序。
  接口域名不需要 www.geekpark.net 首访 403 + Set-Cookie 跳转下发的 cookie
- 量子位 每日最新：首页 ``div.article_list`` 的 ``div.picture_text``（首屏 20 条）。
  官方 RSS 只有 10 条、CDN 缓存约 1 小时、还混着首页顶部轮播里的置顶文章，不用。
  首页只放行浏览器 UA（curl / python-httpx 缺省 UA 403），按项目缺省 Chrome UA 请求
- 雷锋网 每日更新：首页 ``div.lph-pageList div.list ul > li``（首屏 21 条，含编辑插在中间的旧文）。
  官方 RSS 20 条全文约 1.2 MB 且与首页不完全一致，不用；首页里注释掉的翻页地址 /page/2 被
  WAF 拦（403），只取首页不翻页
量子位、雷锋网首页只显示相对时间（「2小时前」「昨天 18:56」「09月28日 18:36」「2026-09-27」），
按北京时间换算（「N小时前」精度只到小时），以响应 ``Date`` 头（Date 减 Age，页面生成时刻）为基准，
不用本机当前时间——两站都走腾讯云 CDN，拿到的可能是缓存副本。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "cn-tech-media"

_TYPE_MAP: dict[str, str] = {
    "ifanr-latest": "爱范儿 · 每日最新",
    "geekpark-hot-week": "极客公园 · 七日热门",
    "qbitai-latest": "量子位 · 每日最新",
    "leiphone-latest": "雷锋网 · 每日更新",
}

_DEFAULT_TYPE = "ifanr-latest"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "国内科技媒体",
    "description": "爱范儿每日最新、极客公园七日热门、量子位与雷锋网首页最新文章。",
    "link": "https://www.ifanr.com/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_CHINA_TZ = timezone(timedelta(hours=8))
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_JSON_ACCEPT = "application/json, text/plain, */*"
_FEED_ACCEPT = "application/rss+xml,application/xml,text/xml"
# 量子位首页拦程序 UA（curl / python-httpx 缺省 UA 403），浏览器 UA 200；其余站点不限 UA
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

IFANR_FEED = "https://www.ifanr.com/feed"
GEEKPARK_HOT = "https://mainssl.geekpark.net/api/v1/posts/hot_in_week?per=7"
QBITAI_HOME = "https://www.qbitai.com/"
LEIPHONE_HOME = "https://www.leiphone.com/"


# ---------------------------------------------------------------- 通用


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _plain(fragment: Any, limit: int | None = None) -> str:
    """HTML 片段转纯文本（极客公园 abstract、爱范儿 RSS description 带内联标签）。"""
    text = _text(BeautifulSoup(str(fragment or ""), "lxml"))
    return text[:limit] if limit else text


def _img(node: Tag | None) -> str | None:
    if not node:
        return None
    src = node.get("data-original") or node.get("data-src") or node.get("src")
    return str(src) if isinstance(src, str) and src.startswith("http") else None


def _page_now(headers: dict[str, Any]) -> datetime:
    """页面生成时刻（相对时间换算基准）：Date 减 Age；没有 Date 头或解析不了时用当前北京时间。"""
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


def relative_time(text: str, now: datetime) -> int | None:
    """首页显示时间 → Unix 秒（北京时间）：刚刚 / N分钟前 / N小时前 / 昨天 HH:MM / 前天 HH:MM /
    MM月DD日 [HH:MM] / YYYY-MM-DD [HH:MM]。「N小时前」只能精确到小时；只有日期的取当天 0 点；
    认不出返回 None。now 是页面生成时刻（响应 Date 头），不是本机当前时间。"""
    value = re.sub(r"\s+", " ", text or "").strip()
    if value == "刚刚":
        return int(now.timestamp())
    match = re.fullmatch(r"(\d+)\s*(分钟|小时)前", value)
    if match:
        delta = timedelta(minutes=int(match.group(1))) if match.group(2) == "分钟" else timedelta(hours=int(match.group(1)))
        return int((now - delta).timestamp())
    match = re.fullmatch(r"(昨天|前天) (\d{1,2}):(\d{2})", value)
    if match:
        day = now - timedelta(days=1 if match.group(1) == "昨天" else 2)
        return int(day.replace(hour=int(match.group(2)), minute=int(match.group(3)), second=0, microsecond=0).timestamp())
    match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日(?: (\d{1,2}):(\d{2}))?", value)
    if match:
        moment = datetime(
            now.year, int(match.group(1)), int(match.group(2)),
            int(match.group(3) or 0), int(match.group(4) or 0), tzinfo=_CHINA_TZ,
        )
        if moment > now + timedelta(days=1):  # 跨年：12 月的文章在 1 月显示成「12月30日」
            moment = moment.replace(year=now.year - 1)
        return int(moment.timestamp())
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?: (\d{1,2}):(\d{2}))?", value)
    if match:
        return int(
            datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                int(match.group(4) or 0), int(match.group(5) or 0), tzinfo=_CHINA_TZ,
            ).timestamp()
        )
    return None


# ---------------------------------------------------------------- 爱范儿（RSS）


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _ifanr_creators(xml: str) -> dict[str, str]:
    """{链接(去 query): dc:creator}。utils.feed 的 parse_feed 在 bs4 xml 模式下读不到带前缀的
    dc:creator（标签名被剥成 creator），爱范儿作者单独补一层。"""
    soup = BeautifulSoup(xml, "xml")
    creators: dict[str, str] = {}
    for node in soup.find_all("item"):
        link = node.find("link")
        creator = next(
            (tag.get_text(" ", strip=True) for tag in node.find_all() if tag.name and tag.name.lower().endswith("creator")),
            "",
        )
        if link and creator:
            creators[_strip_query(link.get_text("", strip=True).strip())] = creator
    return creators


def parse_ifanr_feed(xml: str) -> list[ListItem]:
    creators = _ifanr_creators(xml)
    items: list[ListItem] = []
    for entry in parse_feed(xml):  # 保留 feed 原顺序（与首页「最新」tab 相同）
        url = _strip_query(entry.url)  # RSS 链接带 ?utm_source=rss&utm_medium=rss&utm_campaign=
        match = re.search(r"ifanr\.com/(?:\w+/)?(\d+)$", url)
        items.append(
            entry.model_copy(
                update={"id": match.group(1) if match else url, "url": url, "mobileUrl": url, "author": creators.get(url) or entry.author}
            )
        )
    return items


# ---------------------------------------------------------------- 极客公园


def parse_geekpark_hot(payload: dict[str, Any]) -> list[ListItem]:
    posts = payload.get("posts")
    if not isinstance(posts, list):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"geekpark hot_in_week has no posts list: {str(payload)[:200]}"
        )
    items: list[ListItem] = []
    for row in posts:
        if not isinstance(row, dict) or not row.get("id") or not row.get("title"):
            continue
        authors = [a for a in row.get("authors") or [] if isinstance(a, dict)]
        url = f"https://www.geekpark.net/news/{row['id']}"  # 组件里的链接 "/news/" + id
        items.append(
            ListItem(
                id=row["id"],
                title=_plain(row["title"]) or str(row["title"]).strip(),
                url=url,
                mobileUrl=url,
                hot=row.get("views"),  # 列表按 views 倒序
                cover=row.get("cover_url") or None,
                author=authors[0].get("nickname") if authors else None,
                desc=_plain(row.get("abstract"), 500) or None,
                timestamp=get_time(row.get("published_timestamp")),
            )
        )
    return items


# ---------------------------------------------------------------- 量子位 / 雷锋网


def parse_qbitai_home(page: str, now: datetime) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    box = soup.select_one("div.article_list")
    if not isinstance(box, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            "qbitai home page has no div.article_list (page changed)"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in box.select(":scope > div.picture_text"):
        anchor = card.select_one("h4 a[href]")
        href = str(anchor.get("href") or "") if anchor else ""
        match = re.search(r"/(\d+)\.html", href)
        if not anchor or not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        desc = " ".join(t for t in (_text(p) for p in card.select(".text_box > p")) if t)
        items.append(
            ListItem(
                id=match.group(1),
                title=_text(anchor),
                url=href,
                mobileUrl=href,
                cover=_img(card.select_one(".picture img")),
                author=_text(card.select_one(".author")) or None,
                desc=desc or None,
                timestamp=get_time(relative_time(_text(card.select_one(".time")), now)),
            )
        )
    return items


def parse_leiphone_home(page: str, now: datetime) -> list[ListItem]:
    soup = BeautifulSoup(page, "lxml")
    listing = soup.select_one("div.lph-pageList div.list ul")
    if not isinstance(listing, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            "leiphone home page has no div.lph-pageList list (page changed)"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for li in listing.select(":scope > li"):
        anchor = li.select_one("a.headTit[href]")
        href = str(anchor.get("href") or "") if anchor else ""
        match = re.search(r"/category/\w+/(\w+)\.html", href)
        if not anchor or not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        items.append(
            ListItem(
                id=match.group(1),
                title=str(anchor.get("title") or "") or _text(anchor),
                url=href,
                mobileUrl=href,
                cover=_img(li.select_one(".img img")),
                author=_text(li.select_one("a.aut")) or None,
                desc=_text(li.select_one(".des")) or None,
                timestamp=get_time(relative_time(_text(li.select_one(".time")), now)),
            )
        )
    return items


# ---------------------------------------------------------------- 入口


async def _fetch_page(url: str, board: str, no_cache: bool, accept: str = _HTML_ACCEPT) -> tuple[str, dict[str, Any], RequestResult]:
    result = await get(
        url=url,
        headers={**_BASE_HEADERS, "Accept": accept},
        no_cache=no_cache,
        response_type="text",
        origin_info=True,  # 相对时间换算需要响应 Date / Age 头
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
    if board == "ifanr-latest":
        result = await get(
            url=IFANR_FEED,
            headers={**_BASE_HEADERS, "Accept": _FEED_ACCEPT},
            no_cache=no_cache,
            response_type="text",
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        items = parse_ifanr_feed(str(result.data))
        from_cache, update_time = result.from_cache, result.update_time
    elif board == "geekpark-hot-week":
        result = await get(
            url=GEEKPARK_HOT,
            headers={**_BASE_HEADERS, "Accept": _JSON_ACCEPT},
            no_cache=no_cache,
            response_type="json",
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        items = parse_geekpark_hot(result.data if isinstance(result.data, dict) else {})
        from_cache, update_time = result.from_cache, result.update_time
    elif board == "qbitai-latest":
        page, headers, result = await _fetch_page(QBITAI_HOME, board, no_cache)
        items = parse_qbitai_home(page, _page_now(headers))
        from_cache, update_time = result.from_cache, result.update_time
    else:
        page, headers, result = await _fetch_page(LEIPHONE_HOME, board, no_cache)
        items = parse_leiphone_home(page, _page_now(headers))
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
