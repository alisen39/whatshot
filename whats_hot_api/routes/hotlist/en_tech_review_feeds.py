"""英文科技评测与行业媒体 feed —— CNET / TechRadar / Tom's Guide / ZDNET 等英文科技媒体的官方 feed。

迁移自 board_api en_tech_review_feeds 单元（26 个已完成榜，现存 25 个，多站点一个路由；PCMag 与
CNET How To 不做：前者全站 Cloudflare JS 挑战页，后者原站栏目已下线，见 board_api README）。

- 24 个子榜用站点官方 RSS / Atom feed，保留 feed 原顺序输出（原站顺序，不能按时间重排：
  Dark Reading 的活动预告带未来日期、CNET 的 Atom 按 ``<updated>`` 排序而 timestamp 取首发
  ``<published>``，重排会改变口径），feed 给多少条输出多少条，不截断
- CNET Reviews 解析栏目页 HTML（没有可用的 feed，/rss/reviews/ 是 404）：按页面顺序先取头部
  "REVIEWS"区块（4 条 list-entry 标题 + 5 张 grid-entry 卡片），再接"LATEST REVIEWS"列表
  （一页 15 条），同一链接只留第一次的位置，封面 / 摘要 / 发布日从后面的卡片补齐。
  Tech / Home / Wellness 是分类展示区（带自己的 .ccb-header__title），不是置顶区块，遇到就停
- SpaceNews AI 标签页已因上游不可达下线
- 反爬口径：全程不传 User-Agent（httpx 缺省 UA 即 python-httpx/<版本>，如实表明是程序）。
  WordPress VIP 托管的 Rest of World 对冒充浏览器的请求返回 403
  "Checking your browser..."（JS 工作量证明），对程序 UA 直接 200，该子榜显式带上
  程序 UA 以免共享客户端将来加默认浏览器 UA 时被 403；其余源对 UA 不敏感
  （board_api min_request 实测程序 UA 全部 200、条数相同）。程序 UA 只拿得到该站
  边缘缓存里的内容，缓存未命中时上游 429（此时 httpx raise_for_status 直接抛错），
  稍后再试，不换 UA、不执行任何校验脚本
- 请求遇到挑战壳（Cloudflare "Just a moment..."、WordPress VIP "Checking your browser..."，
  200 状态壳页时）严格报错，不降级为空榜
- timestamp 统一毫秒；feed 取 pubDate / published（CNET、ZDNET 的 Atom 首发时间）；
  CNET Reviews 最新列表的 .entry-date 只到日，按美东 0 点换算；Dark Reading 活动预告的
  未来日期照 feed 原样保留
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import NamedTuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "en-tech-review-feeds"


class _Feed(NamedTuple):
    site: str  # 站点名，拼进 type 标签
    column: str  # 栏目名，拼进 type 标签
    url: str  # feed 地址（kind 不是 feed 时是栏目页）
    page: str  # 原站栏目页，写进 RouterData.link
    kind: str = "feed"  # feed：RSS / Atom；cnet：CNET Reviews 栏目页
    program_ua: bool = False  # True：必须用程序 UA（不能是浏览器 UA），显式带上 python-httpx UA


# 声明序第一个是默认榜（cnet-latest 与 board_api 缺省子榜一致）
_FEEDS: dict[str, _Feed] = {
    "cnet-latest": _Feed("CNET", "全站最新", "https://www.cnet.com/rss/all/", "https://www.cnet.com/"),
    "404media-latest": _Feed("404 Media", "全站最新", "https://www.404media.co/rss/", "https://www.404media.co/"),
    "9to5google-latest": _Feed("9to5Google", "全站最新", "https://9to5google.com/feed/", "https://9to5google.com/"),
    "cnet-deals": _Feed("CNET", "Deals", "https://www.cnet.com/rss/deals/", "https://www.cnet.com/deals/"),
    "cnet-news": _Feed("CNET", "News", "https://www.cnet.com/rss/news/", "https://www.cnet.com/news/"),
    "cnet-reviews": _Feed("CNET", "Reviews", "https://www.cnet.com/reviews/", "https://www.cnet.com/reviews/", "cnet"),
    "cnet-smart-home": _Feed("CNET", "Smart Home", "https://www.cnet.com/rss/smart-home/", "https://www.cnet.com/home/smart-home/"),
    "darkreading-latest": _Feed("Dark Reading", "全站最新", "https://www.darkreading.com/rss.xml", "https://www.darkreading.com/"),
    "eetimes-latest": _Feed("EE Times", "全站最新", "https://www.eetimes.com/feed/", "https://www.eetimes.com/"),
    "gsmarena-latest": _Feed(
        "GSMArena", "Latest articles", "https://www.gsmarena.com/rss-news-reviews.php3", "https://www.gsmarena.com/news.php3"
    ),
    "infoworld-latest": _Feed("InfoWorld", "全站最新", "https://www.infoworld.com/feed/", "https://www.infoworld.com/"),
    "macstories-latest": _Feed("MacStories", "全站最新", "https://www.macstories.net/feed/", "https://www.macstories.net/"),
    "macworld-latest": _Feed("Macworld", "全站最新", "https://www.macworld.com/feed", "https://www.macworld.com/"),
    "crunchbase-latest": _Feed("Crunchbase News", "全站最新", "https://news.crunchbase.com/feed/", "https://news.crunchbase.com/"),
    # WordPress VIP 对浏览器 UA 返回 403 "Checking your browser..."（JS 工作量证明），
    # 对如实标明自己是程序的 UA 直接给数据，所以这两个显式带程序 UA
    "restofworld-latest": _Feed(
        "Rest of World", "全站最新", "https://restofworld.org/feed/latest/", "https://restofworld.org/", program_ua=True
    ),
    "techradar-best": _Feed("TechRadar", "Best", "https://www.techradar.com/feeds/articletype/best", "https://www.techradar.com/best"),
    "techradar-news": _Feed("TechRadar", "News", "https://www.techradar.com/feeds/articletype/news", "https://www.techradar.com/news"),
    "techradar-reviews": _Feed(
        "TechRadar", "Reviews", "https://www.techradar.com/feeds/articletype/review", "https://www.techradar.com/reviews"
    ),
    "techradar-latest": _Feed("TechRadar", "全站最新", "https://www.techradar.com/feeds.xml", "https://www.techradar.com/"),
    "newstack-latest": _Feed("The New Stack", "全站最新", "https://thenewstack.io/feed/", "https://thenewstack.io/"),
    "tomsguide-ai": _Feed("Tom's Guide", "AI", "https://www.tomsguide.com/feeds/tag/ai", "https://www.tomsguide.com/ai"),
    "tomsguide-phones": _Feed("Tom's Guide", "Phones", "https://www.tomsguide.com/feeds/tag/phones", "https://www.tomsguide.com/phones"),
    "tomsguide-latest": _Feed("Tom's Guide", "全站最新", "https://www.tomsguide.com/feeds.xml", "https://www.tomsguide.com/"),
    # tophub "Latest news" 的旧地址 /news/rss.xml 已 301 到这里，直接请求跳转后的地址。
    # 栏目页写首页（feed 的 alternate 链接）：www.zdnet.com/news/ 会 301 到一篇无关文章
    "zdnet-news": _Feed("ZDNET", "news", "https://www.zdnet.com/rss/news/", "https://www.zdnet.com/"),
    # tophub "人工智能" 的旧地址 /topic/artificial-intelligence/rss.xml 已 301 到新闻 feed；
    # 按榜名取 AI 专题 feed（board_api 证据已定口径）
    "zdnet-ai": _Feed(
        "ZDNET", "Artificial Intelligence", "https://www.zdnet.com/rss/topic/artificial-intelligence/", "https://www.zdnet.com/topic/artificial-intelligence/"
    ),
}

type_map: dict[str, str] = {key: f"{feed.site} · {feed.column}" for key, feed in _FEEDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "英文科技评测与行业媒体 feed",
    "description": "CNET、TechRadar、Tom's Guide、ZDNET、9to5Google、Macworld、MacStories、GSMArena、Dark Reading、EE Times 等英文科技媒体的官方 feed",
    "link": "https://www.cnet.com/",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}

_ACCEPT_FEED = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
_ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
# httpx 缺省 UA（python-httpx/<版本>），如实标明是程序；WordPress VIP 只对它给数据
_PROGRAM_UA = f"python-httpx/{httpx.__version__}"
_CNET_TZ = ZoneInfo("America/New_York")  # CNET 卡片日期是美东时间


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", next(iter(type_map)))
    if board not in _FEEDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _get_board(_FEEDS[board], board, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": _FEEDS[board].page},
        type=type_map[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_board(feed: _Feed, board: str, no_cache: bool) -> dict:
    headers = {"Accept": _ACCEPT_FEED if feed.kind == "feed" else _ACCEPT_HTML}
    if feed.program_ua:
        headers["User-Agent"] = _PROGRAM_UA
    result = await get(
        url=feed.url,
        headers=headers,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    body = str(result.data)
    _reject_challenge(body, feed)
    if feed.kind == "feed":
        items = _parse_feed(body)
    else:  # cnet
        items = _parse_cnet_reviews(body, feed.page)
    if not items:
        raise RuntimeError(f"{feed.site} · {feed.column} parsed no items (challenge page or layout change): {feed.url}")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _reject_challenge(body: str, feed: _Feed) -> None:
    """识别 200 状态的挑战壳页（403/429 在 http_client 里已 raise_for_status）。只报错，不执行校验脚本。"""
    head = body[:3000]
    if "Just a moment..." in head:
        raise RuntimeError(
            f"{feed.site} returned a Cloudflare challenge page (Just a moment...): {feed.url}. "
            "The request keeps the program UA; retry later instead of faking a browser"
        )
    if "Checking your browser" in head:
        raise RuntimeError(
            f"{feed.site} returned a WordPress VIP browser-check page (Checking your browser...): {feed.url}. "
            "The request keeps the program UA; retry later instead of running the proof-of-work script"
        )


# ---------------------------------------------------------------- feed 解析（保留原顺序）


def _parse_feed(xml: str) -> list[ListItem]:
    """RSS / Atom 通用解析，保留 feed 原顺序。id 取 guid/id（没有则用链接），
    desc 去 HTML 截 500 字，cover 依次取 media:* / image / enclosure / 摘要第一张图。"""
    soup = BeautifulSoup(xml, "xml")
    nodes = soup.find_all("item") or soup.find_all("entry")
    items: list[ListItem] = []
    for node in nodes:
        # 有的 feed 实体转义两次（&amp;#8217;），解析后还剩一层，再解一次才是页面标题
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
    """RFC 822（RSS pubDate）或 ISO 8601（Atom published/updated）→ 毫秒；解析不了或非正数留空。"""
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


# ---------------------------------------------------------------- CNET Reviews（HTML）


def _iso_ms(value: object) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(datetime.fromisoformat(value.strip()).timestamp() * 1000)
    except ValueError:
        return None


def _card_time(card: Tag) -> tuple[int | None, bool]:
    """卡片日期 → (毫秒, 是否发布日)。LATEST REVIEWS 列表（entry-archive）的 entry-date 是发布日
    （与文章页 article:published_time 同一天），只到日，按美东 0 点；精选区（grid-entry）的
    time@datetime 实测有时是修改时间，只在没有发布日时用。"""
    date = card.select_one(".entry-date")
    if date:
        text = re.sub(r"\s+", " ", date.get_text(" ", strip=True)).strip()
        try:
            day = datetime.strptime(text, "%B %d, %Y").replace(tzinfo=_CNET_TZ)
            return int(day.timestamp() * 1000), True
        except ValueError:
            pass
    stamp = card.find("time")
    ms = _iso_ms(stamp.get("datetime")) if stamp else None
    return (ms, False) if ms else (None, False)


_CNET_CARDS = "article.list-entry, article.grid-entry, article.entry-archive"


def _cnet_page_cards(main: Tag) -> list[Tag]:
    """Reviews 页按页面顺序的两段：
    1. 头部"REVIEWS"区块：页面最上方的 curated-content 块（c-ccb），4 条 list-entry 标题 + 5 张 grid-entry 卡片。
       后面的 Tech / Home / Wellness 块各带分类标题（.ccb-header__title），是分类展示区，遇到就停
    2. "LATEST REVIEWS"列表（div.zd-post-type-archive 里的 entry-archive，一页 15 条，按发布日倒序）"""
    head: list[Tag] = []
    blocks = [b for b in main.select("div.c-ccb") if b.find_parent("div", class_="c-ccb") is None]
    for block in blocks:
        if block.select_one(".ccb-header__title"):
            break
        head += block.select(_CNET_CARDS)
    archive = main.select_one("div.zd-post-type-archive")
    latest = archive.select("article.entry-archive") if archive else []
    if not head or not latest:
        raise RuntimeError(
            f"CNET Reviews page structure changed: head REVIEWS block has {len(head)} cards, "
            f"LATEST REVIEWS list has {len(latest)} entries"
        )
    return head + latest


def _parse_cnet_reviews(html: str, page: str) -> list[ListItem]:
    """头部 REVIEWS 区块 + LATEST REVIEWS 列表，按页面顺序；同一链接出现多次时只留第一次的位置，
    封面 / 摘要 / 发布日从后面的卡片补齐（头部的 5 张卡片就是最新列表的前 5 篇）。"""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    order: list[str] = []
    found: dict[str, dict] = {}
    for card in _cnet_page_cards(main):
        link = card.select_one("h2 a[href], h3 a[href]")
        if not link:
            continue
        href = link.get("href")
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
        if not isinstance(href, str) or not href or not title:
            continue
        url = urljoin(page, href)
        img = card.find("img")
        src = img.get("src") if img else None
        ts, is_publish = _card_time(card)
        rec = found.get(url)
        if rec is None:
            order.append(url)
            rec = found[url] = {"title": title, "cover": None, "desc": None, "ts": None, "publish": False}
        if not rec["cover"] and isinstance(src, str) and src.startswith("http"):
            rec["cover"] = src
        excerpt = card.select_one(".grid-entry__excerpt")
        if not rec["desc"] and excerpt is not None:
            rec["desc"] = _normalize_text(excerpt.get_text(" ", strip=True))
        if ts and (rec["ts"] is None or (is_publish and not rec["publish"])):
            rec["ts"], rec["publish"] = ts, is_publish
    return [
        ListItem(id=url, title=found[url]["title"], url=url, mobileUrl=url, cover=found[url]["cover"], desc=found[url]["desc"], timestamp=found[url]["ts"])
        for url in order
    ]
