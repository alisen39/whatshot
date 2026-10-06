"""杂志与人文网站(FT中文网、三联生活周刊、國家地理雜誌中文網、科学网、
第一财经杂志、哈佛商业评论、环球科学;公开页面 / 原站接口 / 官方 RSS,不登录、无 cookie)。

board_api 单元 `tmp/board_api/magazine_sites` 的 1:1 迁移,证据见该目录 README、
`verify/header_matrix.md`、`verify/adversarial_review.md`、`verify/fallback_check.md`。
原 12 个子榜(日经中文网已因上游不可达下线,现存 11 个;子榜键"站点-栏目";FT"十大热门文章"与"一周十大热门文章"是同一个匿名可见
的一周热门列表,两个 tophub 节点共用 ft-hot-weekly):

- FT 中文网:频道页 /channel/*.html 对匿名 429(TG-ANON-HEAVY-LOCKDOWN),三个榜都不走
  频道页。ft-hot-weekly 取首页右栏"热门文章"区块(div.mps > ul.top10;与"热门付费文章"
  区分:标题文字必须是"热门文章"),条目顺序以页面为准,摘要/日期按链接路径从官方 RSS
  hotstoryby7day 对上;首页 429 或没有该区块时退回 RSS 前 10,message 注明
  (fallback_check 实测)。ft-news、ft-feed 直接用官方 RSS /rss/news、/rss/feed
- 三联生活周刊:栏目页 /column/1(封面故事,Nuxt SSR)的接口 getFollowTagContentList
  (tagId=1、type=3、sort=2、pgSize=20;header_matrix:type/sort 去掉后返回别的列表)
- 國家地理雜誌中文網(繁体):首页 section.lastest"最新探索";環境與保育文章總匯页
  section.content-all(去掉右栏 .article-link-right"熱門精選")
- 科学网:新闻首页"头 条""要 闻"两个区块;"更多"页(topnews.aspx/indexyaowen.aspx)
  按 id 补完整标题、作者、时间(要闻区块把长标题截成"…"),右栏 #topnews 一周排行不算。
  头条区块是编辑挑的(常放站外链接),站外链接与不在"更多"页第 1 页的稿件没有作者和时间
  (adversarial_review #14)
- 第一财经杂志:api.cbnweek.com/v5/first_page_infos?per=8&page=1,
  X-Signature = Base64(md5(前缀+参数值按序拼接+后缀)的 hex)(前端 getRequest 算法,
  本地复现);当前服务端不校验签名,照页面带上
- 哈佛商业评论中文版:hbrchina.org 已 301 到 www.hbrcitic.com,接口
  newsapi-hbr.caijingmobile.com/article/list?last_id=&token=&client_type=1;
  client_type 必需(不带或 0 返回停在 2025-09 的另一份列表,正是 tophub 快照内容);
  首屏 = 焦点第 1 条 + 普通列表
- 环球科学:首页 WordPress 主循环 article.mg-posts-sec-post(10 篇,置顶排最前)

爱思想 3 个榜本机受阻(公司上网策略)、中国国家地理网"热度榜"列表停更,都不在 type 里,
见 board_api README。
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "magazine-sites"

_BEIJING = timezone(timedelta(hours=8))

_FT = "https://www.ftchinese.com"
_FT_FEEDS = {"ft-news": "/rss/news", "ft-feed": "/rss/feed"}
_FT_HOT_FEED = "/rss/hotstoryby7day"
_LIFEWEEK_LIST = (
    "https://www.lifeweek.com.cn/api/userWebFollow/getFollowTagContentList"
    "?pgNo=1&tagId=1&type=3&sort=2&pgSize=20&uid="
)
_NATGEO = "https://www.natgeomedia.com"
_SCIENCENET = "https://news.sciencenet.cn/"
_CBN_LIST = "https://api.cbnweek.com/v5/first_page_infos"
_CBN_PER, _CBN_PAGE = 8, 1  # 首页组件 data(){page:1, per:8}
_CBN_SALT = ("64925f300924b0OzZRpXXz5CqIficrntbhjxmb", "CBNWeeklyAPI")
_HBR_LIST = "https://newsapi-hbr.caijingmobile.com/article/list?last_id=&token=&client_type=1"
_HBR_SITE = "https://www.hbrcitic.com/#"
_HQKX = "https://www.huanqiukexue.com/"
_MONTHS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}

# 声明序第一个是默认榜(与 board_api DEFAULT_TYPE=ft-hot-weekly 一致)。
type_map: dict[str, str] = {
    "ft-hot-weekly": "FT中文网 · 十大热门文章（一周）",
    "ft-news": "FT中文网 · 今日焦点",
    "ft-feed": "FT中文网 · 每日更新",
    "lifeweek-cover": "三联生活周刊 · 封面故事",
    "natgeo-latest": "國家地理雜誌中文網 · 最新探索",
    "natgeo-env-articles": "國家地理雜誌中文網 · 環境與保育 文章總匯",
    "sciencenet-top": "科学网 · 首页头条",
    "sciencenet-yaowen": "科学网 · 首页要闻",
    "cbnweek-home": "第一财经杂志 · 首页推荐",
    "hbr-home": "哈佛商业评论 · 首页推荐",
    "huanqiukexue-home": "环球科学 · 首页推荐",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "杂志与人文网站",
    "description": (
        "FT中文网、三联生活周刊、國家地理雜誌中文網、科学网、第一财经杂志、"
        "哈佛商业评论、环球科学的首页区块、栏目列表与官方 RSS"
    ),
    "link": _FT + "/",
    "params": {
        "type": {
            "name": "站点栏目",
            "type": type_map,
        },
    },
}


def cbn_signature(*values: Any) -> str:
    """第一财经 app.*.js getRequest:md5(前缀+参数值按序拼接+后缀)的 hex 串再 Base64。"""
    digest = hashlib.md5(
        (_CBN_SALT[0] + "".join(str(value) for value in values) + _CBN_SALT[1]).encode()
    ).hexdigest()
    return base64.b64encode(digest.encode()).decode()


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _text(element: Tag | None) -> str:
    return _clean(element.get_text(" ", strip=True)) if element is not None else ""


def _attr(element: Tag | None, name: str) -> str:
    value = element.get(name) if element is not None else None
    return str(value).strip() if isinstance(value, str) else ""


def _soup(page_html: str) -> BeautifulSoup:
    # 科学网页面 meta 写 gb2312,响应头与正文实际都是 UTF-8;共享 get 已按响应头解码
    return BeautifulSoup(page_html, "lxml")


def _beijing_ts(text: str, fmt: str) -> int | None:
    try:
        moment = datetime.strptime(text.strip(), fmt).replace(tzinfo=_BEIJING)
    except ValueError:
        return None
    return int(moment.timestamp())


def _cn_date(text: str) -> int | None:
    """"2026年9月15日" / "2026 年 09 月 01 日" → 北京时间当天 0 点(秒,models 统一转毫秒)。"""
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text or "")
    if not match:
        return None
    moment = datetime(
        int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=_BEIJING
    )
    return int(moment.timestamp())


# ---------------------------------------------------------------- FT 中文网


def _ft_path(url: str) -> str:
    return urlsplit(url).path.rstrip("/")


def _ft_hot_rows(page_html: str) -> list[tuple[str, str]]:
    """首页右栏"热门文章"区块的 [(链接, 标题)];"热门付费文章"区块不取(标题文字区分)。"""
    soup = _soup(page_html)
    head = next(
        (
            anchor
            for anchor in soup.select("h2.list-title a[href]")
            if _attr(anchor, "href").endswith("/channel/weekly.html") and _text(anchor) == "热门文章"
        ),
        None,
    )
    box = head.find_parent("div", class_="mps") if head else None
    rows: list[tuple[str, str]] = []
    for anchor in box.select("ul.top10 li a[href]") if box else []:
        href = _attr(anchor, "href")
        if href:
            rows.append((urljoin(_FT + "/", href), _text(anchor)))
    return rows


async def _fetch_ft_hot(no_cache: bool) -> tuple[RequestResult, list[ListItem], str | None]:
    """首页区块为准,RSS 只补摘要/日期;首页 429 或没有区块时退回 RSS 前 10(证据口径)。"""
    feed_result = await get(url=_FT + _FT_HOT_FEED, no_cache=no_cache, response_type="text")
    feed = parse_feed(str(feed_result.data))
    by_path = {_ft_path(item.url): item for item in feed if item.url}
    try:
        home_result = await get(url=_FT + "/", no_cache=no_cache, response_type="text")
    except httpx.HTTPStatusError as exc:
        home_result, note = None, f"FT 首页 HTTP {exc.response.status_code}，改用 RSS hotstoryby7day 前 10"
    else:
        note = None
    items: list[ListItem] = []
    if home_result is not None:
        for url, title in _ft_hot_rows(str(home_result.data)):
            extra = by_path.get(_ft_path(url))
            items.append(
                ListItem(
                    id=url,
                    title=title or (extra.title if extra else url),
                    url=url,
                    mobileUrl=url,
                    cover=extra.cover if extra else None,
                    desc=extra.desc if extra else None,
                    author=extra.author if extra else None,
                    timestamp=extra.timestamp if extra else None,
                )
            )
        if items:
            return home_result, items, None
        note = "FT 首页没有找到\"热门文章\"区块，改用 RSS hotstoryby7day 前 10"
    if not feed:
        raise RuntimeError("FT hot weekly: homepage block missing and RSS feed empty")
    return feed_result, feed[:10], note


async def _fetch_ft_feed(board: str, no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(url=_FT + _FT_FEEDS[board], no_cache=no_cache, response_type="text")
    items = parse_feed(str(result.data))  # 保留 feed 原顺序
    if not items:
        raise RuntimeError(f"FT feed '{board}' parsed no items")
    return result, items


# ---------------------------------------------------------------- 三联生活周刊


async def _fetch_lifeweek(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(url=_LIFEWEEK_LIST, no_cache=no_cache, response_type="json")
    payload = result.data
    rows = (
        payload.get("model", {}).get("articleResponseList")
        if isinstance(payload, dict) and isinstance(payload.get("model"), dict)
        else None
    )
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"Lifeweek payload has no articleResponseList: {str(payload)[:200]}"
        )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not row.get("title"):
            continue
        url = f"https://www.lifeweek.com.cn/article/{row['id']}"
        authors = "、".join(
            _clean(writer.get("name"))
            for writer in row.get("teacherList") or []
            if isinstance(writer, dict) and writer.get("name")
        )
        items.append(
            ListItem(
                id=row["id"],
                title=_clean(row["title"]),
                url=url,
                mobileUrl=url,
                cover=row.get("pic") or None,
                author=authors or None,
                desc=_clean(row.get("summary")) or None,
                hot=row.get("hotNumber"),  # 页面带"hot"图标显示的数
                timestamp=get_time(row.get("pubTime")),  # "YYYY-MM-DD HH:MM:SS"北京时间
            )
        )
    return result, items


# ---------------------------------------------------------------- 國家地理雜誌中文網


def _natgeo_date(text: str) -> int | None:
    """"Sep. 24 2026" / "Aug.08 2026" → 台北时间(UTC+8)当天 0 点。"""
    match = re.search(r"([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2})\s+(\d{4})", text or "")
    if not match or match.group(1).lower() not in _MONTHS:
        return None
    moment = datetime(
        int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)), tzinfo=_BEIJING
    )
    return int(moment.timestamp())


def _natgeo_items(section: Tag) -> list[ListItem]:
    items: list[ListItem] = []
    seen: set[str] = set()
    for heading in section.select("h4"):
        anchor = heading.select_one("a[href*='/article/content-']")
        if anchor is None:  # 电子杂志推广位之类没有文章链接的 h4
            continue
        url = urljoin(_NATGEO + "/", _attr(anchor, "href"))
        match = re.search(r"content-(\d+)\.html", url)
        if not match or url in seen:
            continue
        seen.add(url)
        card = heading.parent if isinstance(heading.parent, Tag) else None
        date = card.find("h6") if card else None
        category = card.find("h5") if card else None
        # 配图在同一张卡片的外层 <a> 里:往上找第一个带 img 的祖先
        image = None
        node = heading.parent
        while isinstance(node, Tag) and node is not section and image is None:
            image = node.find("img")
            node = node.parent
        cover = (_attr(image, "data-src") or _attr(image, "src")) if isinstance(image, Tag) else ""
        items.append(
            ListItem(
                id=match.group(1),
                title=_text(anchor) or _attr(anchor, "aria-label"),
                url=url,
                mobileUrl=url,
                cover=cover or None,
                desc=(_text(category).rstrip("｜|").strip() or None) if category else None,
                timestamp=get_time(_natgeo_date(_text(date))),
            )
        )
    return items


async def _fetch_natgeo(board: str, no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    url = _NATGEO + "/" if board == "natgeo-latest" else _NATGEO + "/environment/article/index.html"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    soup = _soup(str(result.data))
    selector = "section.lastest" if board == "natgeo-latest" else "section.content-all"
    section = soup.select_one(selector)
    if section is None:
        raise RuntimeError(f"NatGeo page for '{board}' has no {selector} block (page changed)")
    if board != "natgeo-latest":
        for side in section.select(".article-link-right"):
            side.decompose()  # 右栏"熱門精選"不是这个列表
    items = _natgeo_items(section)
    if not items:
        raise RuntimeError(f"NatGeo board '{board}' parsed no items")
    return result, items


# ---------------------------------------------------------------- 科学网


async def _sciencenet_meta(list_url: str, no_cache: bool) -> dict[str, tuple[str, str, int | None]]:
    """"更多"页主列表:id → (完整标题, 作者, 时间)。右栏 #topnews 一周新闻排行不算。"""
    result = await get(url=list_url, no_cache=no_cache, response_type="text")
    soup = _soup(str(result.data))
    for side in soup.select("#topnews"):
        side.decompose()
    meta: dict[str, tuple[str, str, int | None]] = {}
    for anchor in soup.select("a[href*='htmlnews/']"):
        match = re.search(r"/(\d+)\.shtm", _attr(anchor, "href"))
        row = anchor.find_parent("tr")
        cells = row.find_all("td") if row else []
        if not match or match.group(1) in meta or len(cells) < 3:
            continue
        meta[match.group(1)] = (
            _text(anchor),
            _text(cells[1]),
            _beijing_ts(_text(cells[2]), "%Y/%m/%d %H:%M:%S"),
        )
    return meta


async def _fetch_sciencenet(board: str, no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(url=_SCIENCENET, no_cache=no_cache, response_type="text")
    label, list_page = ("头条", "topnews.aspx") if board == "sciencenet-top" else ("要闻", "indexyaowen.aspx")
    soup = _soup(str(result.data))
    head = next(
        (cell for cell in soup.select("td.white") if _text(cell).replace(" ", "") == label),
        None,
    )
    box = head.find_parent("div", class_=["left", "center"]) if head else None
    if box is None:
        raise RuntimeError(f"Sciencenet news home has no \"{label}\" block (page changed)")
    rows: list[tuple[str, str, str | None]] = []
    if board == "sciencenet-top":
        for div in box.select("div.Black"):
            anchor = div.find("a", href=True)
            summary = div.find_next_sibling("div", class_="summary")
            if isinstance(anchor, Tag):
                rows.append((urljoin(_SCIENCENET, _attr(anchor, "href")), _text(anchor), _text(summary) or None))
    else:
        for anchor in box.select("li a[href]"):
            rows.append((urljoin(_SCIENCENET, _attr(anchor, "href")), _text(anchor), None))
    if not rows:
        raise RuntimeError(f"Sciencenet board '{board}' block parsed no rows")
    meta = await _sciencenet_meta(_SCIENCENET + list_page, no_cache)
    items: list[ListItem] = []
    for url, title, desc in rows:
        match = re.search(r"/htmlnews/\d{4}/\d+/(\d+)\.shtm", url)
        full, author, stamp = meta.get(match.group(1), ("", "", None)) if match else ("", "", None)
        if title.endswith("...") and full:
            title = full  # 首页区块把长标题截成"…...",完整标题取"更多"页
        items.append(
            ListItem(
                id=match.group(1) if match else url,  # 站外链接用链接本身
                title=title,
                url=url,
                mobileUrl=url,
                desc=desc,
                author=author or None,
                timestamp=get_time(stamp),
            )
        )
    return result, items


# ---------------------------------------------------------------- 第一财经杂志


async def _fetch_cbnweek(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    url = f"{_CBN_LIST}?per={_CBN_PER}&page={_CBN_PAGE}"
    result = await get(
        url=url,
        headers={
            "X-Signature": cbn_signature(_CBN_PER, _CBN_PAGE),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.cbnweek.com",
            "Referer": "https://www.cbnweek.com/",
        },
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data
    blocks = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"CBN Weekly payload has no data blocks: {str(payload)[:200]}"
        )
    items: list[ListItem] = []
    for block in blocks:
        kind = str(block.get("type") or "") if isinstance(block, dict) else ""
        rows = block.get("data") if isinstance(block, dict) else None
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            # 首页 detail():sound_article → /hot_detail,theme → /read_free,其余 → /article_detail
            route = {"sound_article": "hot_detail", "theme": "read_free"}.get(kind, "article_detail")
            link = f"https://www.cbnweek.com/{route}/{row['id']}"
            shown = kind in ("normal_article", "sound_article", "top_article")  # 页面只对这几类显示"N 阅读"
            items.append(
                ListItem(
                    id=row["id"],
                    title=_clean(row.get("title") or row.get("name")),
                    url=link,
                    mobileUrl=link,
                    cover=row.get("cover_url") or None,
                    hot=row.get("visit_times") if shown else None,
                    timestamp=get_time(row.get("display_time")),  # ISO(UTC),get_time 归一化毫秒
                )
            )
    items = [item for item in items if item.title]
    if not items:
        raise RuntimeError("CBN Weekly homepage parsed no items")
    return result, items


# ---------------------------------------------------------------- 哈佛商业评论中文版


async def _fetch_hbr(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(
        url=_HBR_LIST,
        headers={"Accept": "application/json, text/plain, */*", "Origin": "https://www.hbrcitic.com", "Referer": "https://www.hbrcitic.com/"},
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("code") != 200 or not isinstance(data, dict):
        raise RuntimeError(f"HBR api returned an unexpected payload: {str(payload)[:200]}")
    rows = (data.get("focus_articles") or [])[:1] + (data.get("normal_articles") or [])  # 首屏只用第 1 条焦点
    items: list[ListItem] = []
    for row in rows:
        article = row.get("article") if isinstance(row, dict) else None
        if not isinstance(article, dict) or not article.get("id"):
            continue
        path = "/podcast/detail" if row.get("type") == 22 else "/article/detail"  # TYPE_AUDIO=22
        link = f"{_HBR_SITE}{path}?id={article['id']}"
        author = re.sub(r"\s*[|｜]\s*文\s*$", "", _clean(article.get("author")))  # 署名尾部的"| 文"
        items.append(
            ListItem(
                id=article["id"],
                title=_clean(article.get("title")),
                url=link,
                mobileUrl=link,
                cover=article.get("image_url") or None,
                author=author or None,
                desc=_clean(article.get("description")) or None,
                timestamp=get_time(_cn_date(str(article.get("publish_time") or ""))),  # 日期当天 0 点
            )
        )
    if not items:
        raise RuntimeError("HBR homepage parsed no items")
    return result, items


# ---------------------------------------------------------------- 环球科学


async def _fetch_huanqiukexue(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(url=_HQKX, no_cache=no_cache, response_type="text")
    soup = _soup(str(result.data))
    items: list[ListItem] = []
    for post in soup.select(".mg-posts-sec-inner > article.mg-posts-sec-post"):
        anchor = post.select_one("h4.entry-title a[href]")
        if anchor is None:
            continue
        url = _attr(anchor, "href")
        match = re.search(r"[?&]p=(\d+)", url)
        thumb = post.select_one(".mg-post-thumb")
        cover = re.search(r"url\(['\"]?([^'\")]+)", _attr(thumb, "style"))
        items.append(
            ListItem(
                id=match.group(1) if match else url,
                title=_text(anchor),
                url=url,
                mobileUrl=url,
                cover=cover.group(1) if cover else None,
                author=_text(post.select_one("a.auth")) or None,
                desc=_text(post.select_one(".mg-content")) or None,
                timestamp=get_time(_cn_date(_text(post.select_one(".mg-blog-date")))),
            )
        )
    if not items:
        raise RuntimeError("Huanqiukexue homepage parsed no items")
    return result, items


# ---------------------------------------------------------------- 入口


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in type_map:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")

    message: str | None = None
    if selected == "ft-hot-weekly":
        result, data, message = await _fetch_ft_hot(no_cache)
    elif selected in _FT_FEEDS:
        result, data = await _fetch_ft_feed(selected, no_cache)
    elif selected == "lifeweek-cover":
        result, data = await _fetch_lifeweek(no_cache)
    elif selected.startswith("natgeo-"):
        result, data = await _fetch_natgeo(selected, no_cache)
    elif selected.startswith("sciencenet-"):
        result, data = await _fetch_sciencenet(selected, no_cache)
    elif selected == "cbnweek-home":
        result, data = await _fetch_cbnweek(no_cache)
    elif selected == "hbr-home":
        result, data = await _fetch_hbr(no_cache)
    else:
        result, data = await _fetch_huanqiukexue(no_cache)

    if not data:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"Magazine sites board '{selected}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
        message=message,
    )
