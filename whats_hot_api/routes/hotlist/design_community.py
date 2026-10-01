"""设计社区作品榜 —— Behance / It's Nice That / designboom / 数英网 / 优设网 / 站酷。

迁移自 board_api design_community 单元（14 个已完成榜，多站点一个路由；Dribbble 5 个榜
全站 AWS WAF JS 挑战、站酷文章推荐需登录，不做，见 board_api README）。whatshot 既有
``uisdc`` 路由取的是 /news 页 AI 快讯，不是文章列表，与本路由互不重叠。

- 官方 RSS 3 个：Behance Featured Projects、designboom、数英网，保留 feed 原顺序输出，
  feed 给多少条输出多少条
- It's Nice That：/articles 页服务端渲染，列表在页面内 ``<script id="props">`` 的
  ``data.page.items.edges[].node``（一页 20 条，页头 Insights / Events / Jobs Board 是导航不算条目）
- 优设网 3 个 HTML 页面：/archives（所有文章，一页 40 条）、hot.uisdc.com/posts（热文榜单，
  40 条）、/hunter?od=hot（细节猎人最热门，19 条）；列表里插的"优设情报""产品榜"小组件不是
  条目，跳过。/archives 显示相对时间（"13分钟前 / 3小时前"），以页面生成时刻为基准倒推：
  页面是 WP-Super-Cache 静态缓存，生成时刻取响应 ``Last-Modified`` 头（``Date`` 头只是发出
  时刻，留档差 20 分钟），没有或解析不了时退回 ``Date`` 头，不用本机当前时间；"N天前"只能
  确定是 N~N+1 天前，推不出日期，留空不编
- 站酷推荐 5 个：/discover 页内嵌 ``__NEXT_DATA__`` 的 ``props.pageProps.listResult.data``
  （一页 60 条）；recommendLevel=1/2/3 = 全部推荐 / 编辑精选 / 首页推荐，cate=610 影视、
  33 摄影。首页推荐里夹着少量文章（链接 /article/…），与页面一致，照样输出
- 站酷总榜 2 个：同源接口 ``/p1/ranking/list?p=1&ps=10&type=3``（作品榜）/ ``type=8``
  （文章榜），``ps=10`` 与总榜页首屏一致；不带 rank_id 即最新一期（周榜），type 标签带期数。
  tophub 作品总榜节点停在 2024 年初，照原站最新一期；tophub 文章总榜节点挂的是作品榜内容，
  按榜名取文章榜 type=8
- 反爬口径：带项目缺省浏览器 UA。Behance 对 python-httpx UA 返回 403、站酷返回阿里云 WAF
  挑战页，浏览器 UA 直接通过（board_api header_matrix 实测）；返回阿里云 WAF 挑战壳时严格
  报错，不执行 JS、不绕挑战
- timestamp 统一毫秒；优设热文 / 站酷总榜只有日期，按北京时间当天 0 点；细节猎人不显示
  时间，留空。hot：优设热文阅读数（"2.8w 阅读"→28000）、站酷浏览数（discover viewCount /
  总榜 view）；其余源不提供热度
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, NamedTuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "design-community"

_ZCOOL = "站酷"
_UISDC = "优设网"


class _Source(NamedTuple):
    site: str  # 站点名，拼进 type 标签
    column: str  # 栏目名，拼进 type 标签
    url: str  # 取数地址
    page: str  # 原站页面，写进 RouterData.link
    parser: str  # feed / itsnicethat / uisdc-archives / uisdc-hot / uisdc-hunter / zcool-discover / zcool-rank


# 声明序第一个是默认榜（zcool-editor-picks 与 board_api 缺省子榜一致）
_SOURCES: dict[str, _Source] = {
    "zcool-editor-picks": _Source(_ZCOOL, "编辑精选", "https://www.zcool.com.cn/discover?recommendLevel=2", "https://www.zcool.com.cn/discover?recommendLevel=2", "zcool-discover"),
    "behance-featured": _Source("Behance", "Featured Projects", "https://www.behance.net/feeds/projects", "https://www.behance.net/galleries", "feed"),
    "itsnicethat-articles": _Source("It's Nice That", "Work", "https://www.itsnicethat.com/articles", "https://www.itsnicethat.com/articles", "itsnicethat"),
    "designboom-latest": _Source("designboom", "最新文章", "https://www.designboom.com/feed/", "https://www.designboom.com/", "feed"),
    "digitaling-latest": _Source("数英网 DIGITALING", "最新内容", "https://www.digitaling.com/rss", "https://www.digitaling.com/", "feed"),
    "uisdc-latest": _Source(_UISDC, "所有文章（最新）", "https://www.uisdc.com/archives", "https://www.uisdc.com/archives", "uisdc-archives"),
    "uisdc-hot-posts": _Source(_UISDC, "热文榜单", "https://hot.uisdc.com/posts", "https://hot.uisdc.com/posts", "uisdc-hot"),
    "uisdc-hunter-hot": _Source(_UISDC, "细节猎人 · 最热门", "https://www.uisdc.com/hunter?od=hot", "https://www.uisdc.com/hunter?od=hot", "uisdc-hunter"),
    "zcool-work-rank": _Source(_ZCOOL, "作品总榜", "https://www.zcool.com.cn/p1/ranking/list?p=1&ps=10&type=3", "https://www.zcool.com.cn/top/index.do", "zcool-rank"),
    "zcool-article-rank": _Source(_ZCOOL, "文章总榜", "https://www.zcool.com.cn/p1/ranking/list?p=1&ps=10&type=8", "https://www.zcool.com.cn/top/index.do", "zcool-rank"),
    "zcool-all-recommend": _Source(_ZCOOL, "全部推荐", "https://www.zcool.com.cn/discover?recommendLevel=1", "https://www.zcool.com.cn/discover?recommendLevel=1", "zcool-discover"),
    "zcool-home-picks": _Source(_ZCOOL, "首页推荐", "https://www.zcool.com.cn/discover?recommendLevel=3", "https://www.zcool.com.cn/discover?recommendLevel=3", "zcool-discover"),
    "zcool-film-editor-picks": _Source(_ZCOOL, "影视 · 编辑精选", "https://www.zcool.com.cn/discover?cate=610&recommendLevel=2", "https://www.zcool.com.cn/discover?cate=610&recommendLevel=2", "zcool-discover"),
    "zcool-photo-editor-picks": _Source(_ZCOOL, "摄影 · 编辑精选", "https://www.zcool.com.cn/discover?cate=33&recommendLevel=2", "https://www.zcool.com.cn/discover?cate=33&recommendLevel=2", "zcool-discover"),
}

type_map: dict[str, str] = {key: f"{source.site} · {source.column}" for key, source in _SOURCES.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "设计社区作品榜",
    "description": "Behance、It's Nice That、designboom、数英网、优设网、站酷的作品 / 文章列表与榜单",
    "link": "https://www.zcool.com.cn/discover",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}

# board_api 全部请求都带这组客户端头（common.http.DEFAULT_HEADERS）；
# Behance 对程序 UA 返回 403、站酷返回阿里云 WAF 挑战页，浏览器 UA 是必需口径
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
_ACCEPT_FEED = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
_ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_JSON = "application/json, text/plain, */*"
_BEIJING = timezone(timedelta(hours=8))
_RELATIVE_UNITS = {"分钟": 60, "小时": 3600}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", next(iter(type_map)))
    if board not in _SOURCES:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    source = _SOURCES[board]
    list_data = await _get_board(source, board, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": source.page},
        type=list_data["type"],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _accept(parser: str) -> str:
    if parser == "feed":
        return _ACCEPT_FEED
    if parser == "zcool-rank":
        return _ACCEPT_JSON
    return _ACCEPT_HTML


async def _get_board(source: _Source, board: str, no_cache: bool) -> dict:
    # 优设"所有文章"的相对时间要以响应 Last-Modified 头为基准，所以带回响应头
    origin_info = source.parser == "uisdc-archives"
    result = await get(
        url=source.url,
        headers={**_BASE_HEADERS, "Accept": _accept(source.parser)},
        no_cache=no_cache,
        response_type="json" if source.parser == "zcool-rank" else "text",
        origin_info=origin_info,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    label = type_map[board]
    what = f"{source.site} · {source.column}"
    if origin_info:
        wrapped = result.data if isinstance(result.data, dict) and isinstance(result.data.get("headers"), dict) else {}
        body = str(wrapped.get("data") or "")
        page_time = _uisdc_page_time(wrapped.get("headers") or {})
        _reject_challenge(body, source)
        items = _parse_uisdc_archives(body, page_time)
    elif source.parser == "feed":
        body = str(result.data)
        _reject_challenge(body, source)
        items = _parse_feed(body)
    elif source.parser == "itsnicethat":
        body = str(result.data)
        _reject_challenge(body, source)
        items = _parse_itsnicethat(body, source.page)
    elif source.parser == "uisdc-hot":
        body = str(result.data)
        _reject_challenge(body, source)
        items = _parse_uisdc_hot(body)
    elif source.parser == "uisdc-hunter":
        body = str(result.data)
        _reject_challenge(body, source)
        items = _parse_uisdc_hunter(body)
    elif source.parser == "zcool-discover":
        body = str(result.data)
        _reject_challenge(body, source)
        items = _parse_zcool_discover(body)
    else:  # zcool-rank
        payload = result.data if isinstance(result.data, dict) else {}
        items, period = _parse_zcool_rank(payload)
        if period:
            label = f"{label} · {period}"
    if not items:
        raise RuntimeError(f"{what} parsed no items (challenge page, login redirect or layout change): {source.url}")
    return {"type": label, "data": items, "from_cache": result.from_cache, "update_time": result.update_time}


def _reject_challenge(body: str, source: _Source) -> None:
    """识别挑战壳页。只识别、报错，不执行 JS、不绕挑战（登录 302 会被 httpx 跟进，
    最终由"解析不到条目"的空解析兜底报错）。"""
    head = body[:3000]
    if 'name="aliyun_waf_aa"' in head:
        raise RuntimeError(
            f"{source.site} returned an Aliyun WAF challenge page: {source.url}. "
            "The request keeps the browser UA from board_api evidence; do not run the challenge JS"
        )
    if "Just a moment..." in head:
        raise RuntimeError(
            f"{source.site} returned a Cloudflare challenge page (Just a moment...): {source.url}. "
            "Do not fake a different UA or run the challenge script"
        )


# ---------------------------------------------------------------- feed（保留原顺序）


def _parse_feed(xml: str) -> list[ListItem]:
    """RSS / Atom 通用解析，保留 feed 原顺序。id 取 guid/id（没有则用链接），
    desc 去 HTML 截 500 字，cover 依次取 media:* / image / enclosure / 摘要第一张图。"""
    soup = BeautifulSoup(xml, "xml")
    nodes = soup.find_all("item") or soup.find_all("entry")
    items: list[ListItem] = []
    for node in nodes:
        title = re.sub(r"\s+", " ", unescape(_tag_text(node, "title"))).strip()
        url = _feed_link(node)
        if not title or not url.startswith(("http://", "https://")):
            continue
        description = _first_tag_text(node, "description", "summary", "content", "content:encoded")
        items.append(
            ListItem(
                id=_tag_text(node, "guid") or _tag_text(node, "id") or url,
                title=title,
                author=_tag_text(node, "dc:creator") or _author_text(node) or _tag_text(node, "source") or None,
                desc=_html_text(description),
                cover=_feed_image(node, description),
                timestamp=_feed_time(_first_tag_text(node, "pubDate", "pubdate", "published", "updated", "dc:date")),
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _feed_link(node: Tag) -> str:
    link = node.find("link")
    if not link:
        return ""
    href = link.get("href")
    return href.strip() if isinstance(href, str) and href else link.get_text("", strip=True)


def _feed_image(node: Tag, description: str) -> str | None:
    for tag_name in ("media:thumbnail", "media:content", "image"):
        tag = node.find(tag_name)
        if tag:
            candidate = tag.get("url") or tag.get_text("", strip=True)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
    enclosure = node.find("enclosure")
    if enclosure:
        candidate = enclosure.get("url")
        media_type = enclosure.get("type") or ""
        if (not media_type or str(media_type).startswith("image/")) and isinstance(candidate, str) and candidate.startswith(
            ("http://", "https://")
        ):
            return candidate
    image = BeautifulSoup(description or "", "lxml").find("img")
    candidate = image.get("src") if image else None
    return candidate if isinstance(candidate, str) and candidate.startswith(("http://", "https://")) else None


def _author_text(node: Tag) -> str:
    author = node.find("author")
    if not author:
        return ""
    name = author.find("name")
    return name.get_text(" ", strip=True) if name else author.get_text(" ", strip=True)


def _tag_text(node: Tag, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _first_tag_text(node: Tag, *names: str) -> str:
    for name in names:
        text = _tag_text(node, name)
        if text:
            return text
    return ""


def _normalize_text(value: object, *, limit: int = 500) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] or None


def _html_text(fragment: str, *, limit: int = 500) -> str | None:
    return _normalize_text(BeautifulSoup(fragment or "", "lxml").get_text(" ", strip=True), limit=limit)


def _feed_time(value: str) -> int | None:
    """RFC 822（RSS pubDate）或 ISO 8601（Atom）→ 毫秒；解析不了或非正数留空。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ms = int(parsedate_to_datetime(text).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            ms = int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return None
    return ms if ms > 0 else None


# ---------------------------------------------------------------- It's Nice That


def _parse_itsnicethat(html: str, page: str) -> list[ListItem]:
    """页面内 <script id="props" type="application/json"> 的 data.page.items.edges[].node（Article）：
    title、url（相对）、publicationDate、standfirst、listingImage.url。页头 Masthead（Insights、
    Events、Jobs Board）是导航不算条目。id 取 url 最后一段（文章 slug）。"""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="props")
    if not isinstance(script, Tag) or not script.string:
        raise RuntimeError("It's Nice That page has no <script id=props> (page changed)")
    data = json.loads(script.string)
    edges = (((data.get("data") or {}).get("page") or {}).get("items") or {}).get("edges")
    if not isinstance(edges, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "It's Nice That props has no data.page.items.edges (page changed)"
        )
    items: list[ListItem] = []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict) or not node.get("title") or not node.get("url"):
            continue
        url = urljoin(page, str(node["url"]))
        image = node.get("listingImage")
        items.append(
            ListItem(
                id=str(node["url"]).rstrip("/").rsplit("/", 1)[-1],
                title=_normalize_text(node["title"], limit=500),
                url=url,
                mobileUrl=url,
                cover=image.get("url") if isinstance(image, dict) else None,
                desc=_html_text(str(node.get("standfirst") or "")),
                timestamp=_feed_time(str(node.get("publicationDate") or "")),
            )
        )
    return items


# ---------------------------------------------------------------- 优设网


def _uisdc_page_time(headers: dict[str, Any]) -> datetime:
    """优设页面的生成时刻（"N分钟前 / N小时前"的换算基准）。页面是 WP-Super-Cache 静态缓存
    （生成时刻与 Last-Modified 头相同），Date 头只是发出时刻（留档差 20 分钟）。
    取 Last-Modified（不晚于 Date 头）；没有或解析不了时用 Date 头，再不行用当前 UTC 时间。"""
    sent = _header_time(headers, "date")
    generated = _header_time(headers, "last-modified")
    if generated is not None and sent is not None:
        return min(generated, sent)
    return generated or sent or datetime.now(UTC)


def _header_time(headers: dict[str, Any], name: str) -> datetime | None:
    raw = next((value for key, value in headers.items() if str(key).lower() == name), None)
    try:
        return parsedate_to_datetime(str(raw)).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _date_seconds(value: str) -> int | None:
    """"2026-09-15" / "2026/09/21" 这类只有日期的值，按北京时间当天 0 点（只有日期精度）。"""
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value.strip())
    if not match:
        return None
    dt = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=_BEIJING)
    return int(dt.timestamp() * 1000)


def _uisdc_time(value: str, now: datetime) -> int | None:
    """所有文章页的时间：7 天内显示"N分钟前 / N小时前 / 2天前"，更早显示"2026/09/21"。
    分钟、小时按页面生成时刻 now 倒推；"N天前"只知道是 N~N+1 天前，推不出日期，留空（不编）；
    日期按北京时间 0 点。"""
    value = value.strip()
    match = re.fullmatch(r"(\d+)\s*(分钟|小时)前", value)
    if match:
        return int(now.timestamp() * 1000) - int(match.group(1)) * _RELATIVE_UNITS[match.group(2)] * 1000
    if value in ("刚刚", "刚才"):
        return int(now.timestamp() * 1000)
    return _date_seconds(value)


def _parse_uisdc_archives(html: str, now: datetime) -> list[ListItem]:
    """div.c-items 下每个 div.category-list-item 是一篇文章（h2.item-title > a）。
    "优设情报"小组件（class 带 category-list-item-news，指向 /news）不是文章，跳过。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in soup.select("div.c-items div.category-list-item"):
        classes = card.get("class") or []
        if "category-list-item-news" in classes:
            continue
        link = card.select_one("h2.item-title > a")
        url = str(link.get("href") or "").strip() if link else ""
        if link is None or not url or url in seen:
            continue
        seen.add(url)
        pid = card.select_one("[pid]")
        author = card.select_one(".u-name")
        img = card.select_one(".item-thumb img")
        when = card.select_one(".meta-time")
        title = str(link.get("title") or "").strip() or link.get_text(" ", strip=True)
        items.append(
            ListItem(
                id=str(pid.get("pid")) if pid is not None and pid.get("pid") else url,
                title=_normalize_text(title),
                url=url,
                mobileUrl=url,
                author=_normalize_text(author.get_text()) if author else None,
                cover=str(img.get("src")) if img is not None and img.get("src") else None,
                timestamp=_uisdc_time(when.get_text(" ", strip=True), now) if when else None,
            )
        )
    return items


def _parse_uisdc_hot(html: str) -> list[ListItem]:
    """热文榜单 div.p-items > div.p-item：h2.item-title > a、item-entry 摘要、meta-author、
    meta-views（"2.8w 阅读"）、meta-date（"2026-09-15"，按北京时间 0 点）。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in soup.select("div.p-items > div.p-item"):
        link = card.select_one("h2.item-title > a")
        url = str(link.get("href") or "").strip() if link else ""
        if link is None or not url or url in seen:
            continue
        seen.add(url)
        entry = card.select_one(".item-entry")
        author = card.select_one(".meta-author a")
        views = card.select_one(".meta-views")
        date = card.select_one(".meta-date")
        items.append(
            ListItem(
                id=url.rstrip("/").rsplit("/", 1)[-1],
                title=_normalize_text(link.get_text(" ", strip=True)),
                url=url,
                mobileUrl=url,
                desc=_normalize_text(entry.get_text(" ", strip=True)) if entry else None,
                author=_normalize_text(author.get_text(" ", strip=True)) if author else None,
                cover=_bg_url(card.select_one(".item-thumb .thumb")),
                hot=_wan(views.get_text()) if views else None,
                timestamp=_date_seconds(date.get_text(strip=True)) if date else None,
            )
        )
    return items


def _wan(value: str) -> int | None:
    """"2.8w 阅读" → 28000，"956 阅读" → 956。"""
    match = re.search(r"(\d+(?:\.\d+)?)\s*([wW万]?)", value or "")
    if not match:
        return None
    number = float(match.group(1))
    return round(number * 10000) if match.group(2) else round(number)


def _bg_url(tag: Tag | None) -> str | None:
    match = re.search(r"background-image:\s*url\(([^)]+)\)", str(tag.get("style") or "") if tag is not None else "")
    return match.group(1).strip("'\" ") if match else None


def _parse_uisdc_hunter(html: str) -> list[ListItem]:
    """细节猎人 div.hunter-list div.items > div.hunter-list-item（data-pid）：h2.item-title > a 的
    title 属性是标题（链接文字前面多一个分类标签）；hunter-entry 摘要；meta-author 的 .prefix
    （"猎人 - "）去掉。"产品榜"小组件（没有 h2.item-title）跳过。列表不显示时间，timestamp 留空；
    评分不是热度，hot 留空。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in soup.select("div.hunter-list div.items > div.hunter-list-item"):
        link = card.select_one("h2.item-title > a")
        url = str(link.get("href") or "").strip() if link else ""
        if link is None or not url or url in seen:
            continue
        seen.add(url)
        title = str(link.get("title") or "").strip()
        if not title:
            tag = link.select_one(".tag")
            if tag is not None:
                tag.extract()
            title = link.get_text(" ", strip=True)
        entry = card.select_one(".hunter-entry p")
        author = card.select_one(".meta-author")
        prefix = author.select_one(".prefix") if author else None
        if prefix is not None:
            prefix.extract()
        img = card.select_one(".item-thumb img")
        items.append(
            ListItem(
                id=str(card.get("data-pid")) if card.get("data-pid") else url,
                title=_normalize_text(title),
                url=url,
                mobileUrl=url,
                desc=_normalize_text(entry.get_text(" ", strip=True)) if entry else None,
                author=_normalize_text(author.get_text(" ", strip=True)) if author else None,
                cover=str(img.get("src")) if img is not None and img.get("src") else None,
            )
        )
    return items


# ---------------------------------------------------------------- 站酷


def _parse_zcool_discover(html: str) -> list[ListItem]:
    """/discover 页面 __NEXT_DATA__ 的 props.pageProps.listResult.data[]：每条 {objectType, content}，
    content.idStr / title / pageUrl / cover / creatorObj.username / publishTime（毫秒）/ viewCount。
    首页推荐里夹着少量文章（链接 /article/…），与页面一致，照样输出。"""
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        raise RuntimeError("Zcool discover page has no __NEXT_DATA__ (page changed)")
    data = json.loads(match.group(1))
    rows = (((data.get("props") or {}).get("pageProps") or {}).get("listResult") or {}).get("data")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "Zcool discover __NEXT_DATA__ has no listResult.data (page changed)"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        content = row.get("content") if isinstance(row, dict) else None
        if not isinstance(content, dict) or not content.get("title") or not content.get("pageUrl"):
            continue
        key = str(content.get("idStr") or content.get("id"))
        if key in seen:
            continue
        seen.add(key)
        creator = content.get("creatorObj")
        items.append(
            ListItem(
                id=key,
                title=_normalize_text(content["title"]),
                url=str(content["pageUrl"]),
                mobileUrl=str(content["pageUrl"]),
                cover=content.get("cover"),
                author=creator.get("username") if isinstance(creator, dict) else None,
                hot=content.get("viewCount"),
                timestamp=get_time(content.get("publishTime")),
            )
        )
    return items


def _parse_zcool_rank(payload: dict[str, Any]) -> tuple[list[ListItem], str]:
    """/p1/ranking/list 的 datas[]：rankingTitle、pageUrl、rankingCoverImage、member.name、
    rankingPublishTime（只有日期，按北京时间 0 点）、view（本期浏览数）。tdk.title 带期数。"""
    if payload.get("resultCode") != "SUCCESS":
        raise RuntimeError(f"zcool ranking API returned non-SUCCESS envelope: {str(payload)[:200]}")
    rows = payload.get("datas")
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("rankingTitle") or not row.get("pageUrl"):
            continue
        url = str(row["pageUrl"])
        key = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
        if key in seen:
            continue
        seen.add(key)
        member = row.get("member")
        items.append(
            ListItem(
                id=key,
                title=_normalize_text(row["rankingTitle"]),
                url=url,
                mobileUrl=url,
                cover=row.get("rankingCoverImage"),
                author=member.get("name") if isinstance(member, dict) else None,
                hot=row.get("view"),
                timestamp=_date_seconds(str(row.get("rankingPublishTime") or "")),
            )
        )
    title = str((payload.get("tdk") or {}).get("title") or "")
    period = re.search(r"第\d+期", title)
    return items, period.group(0) if period else ""
