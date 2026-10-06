"""英文科学、体育与综合媒体 feed(FOX Sports、Apple 支持服务计划、Car and Driver、Aeon、
国家地理、New Scientist、HBR、Scientific American、Science News;官方 feed 与栏目页)。

board_api 单元 ``tmp/board_api/en_science_misc_feeds`` 的 1:1 迁移,证据见该目录 README、
``evidence/index.md`` 与 ``verify/``(newscientist_ua_matrix、min_request、page_vs_output 等)。
16 个子榜(子榜键"站点-栏目";board_api DEFAULT_TYPE=foxsports-top,即声明序第一个):

- 官方 RSS / Atom 10 个:FOX Sports 4 个(地址与 partnerKey 取自官方 RSS 目录页
  foxsports.com/rss-feeds,页面上公开写死的参数)、Car and Driver、Aeon、New Scientist 2 个、
  Scientific American、Science News;条数以 feed 为准,不截断
- FOX Sports Tennis、Olympics 取栏目页不取 feed(官方 feed 已停更:Tennis 最新 2026-06-08、
  Olympics 最新 2023-03-08,栏目页每天更新):/tennis 301 到 /tennis/atp、/olympics 301 到
  /winter-olympics(共享 http_client 跟随跳转),列表在页面 __NUXT_DATA__(devalue 扁平数组)
  的 secondaryNavigationViewModel.content.apiEndpointResponseData.data.results(一页 25 条,
  与页面卡片同序);核对列表 uri 是 tennis/atp/league/2 / olympics/winter/league/2,
  以后跳到别的主题直接报错
- HBR:官方 Atom feed,但标签带 ns6: 前缀、链接是相对路径、配图在 HBR 自定义的
  thumbnail-image-uri 里,utils.feed.parse_feed 一条也解析不出来,单独解析
  (https 版 TLS 握手被断开,官方地址本身就是 http)
- Apple 支持"服务计划":没有 RSS,页面服务端渲染,每个计划一个 section.as-container-column
- 国家地理"每日一图""最新故事":没有 RSS,解析页面内嵌 window['__natgeo__'] JSON
  (服务端渲染用的就是这份数据)
- BoardGameGeek News 不做:页面与 RSS 都是 Cloudflare 挑战页(board_api README 留档)

New Scientist 只拦冒充浏览器的请求(Chrome/Safari/Firefox UA 一律 406 空响应),
程序 UA(python-httpx 缺省)200,按 board_api"可以用程序 UA"的口径不发 User-Agent
(共享 http_client 缺省 UA 就是 python-httpx);其余站点带浏览器 UA。
"""

from __future__ import annotations

import base64
import html as htmllib
import json
import re
from datetime import UTC, datetime
from typing import Any, NamedTuple
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "en-science-misc-feeds"

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

FOX_RSS = "https://api.foxsports.com/v2/content/optimized-rss?partnerKey=MB0Wehpmuj2lUhuRhQaafhBjAJqaPU244mlTDK1i"
FOX_SOCCER_TAGS = (
    "fs/soccer,soccer/epl/league/1,soccer/mls/league/5,soccer/ucl/league/7,soccer/europa/league/8,"
    "soccer/wc/league/12,soccer/euro/league/13,soccer/wwc/league/14,soccer/nwsl/league/20,"
    "soccer/cwc/league/26,soccer/gold_cup/league/32,soccer/unl/league/67"
)
NATGEO_BASE = "https://www.nationalgeographic.com"


class Source(NamedTuple):
    site: str  # 站点名(board_api 响应里写进 title,这里保留在子榜配置)
    column: str  # 栏目名
    url: str  # 取数地址(feed 或页面)
    page: str  # 栏目页,写进 RouterData.link
    parser: str  # feed / hbr / apple / natgeo-potd / natgeo-latest / fox-page
    ua: str | None = _BROWSER_UA  # New Scientist 置 None:不能冒充浏览器,用 httpx 缺省 UA
    list_uri: str | None = None  # fox-page:页面列表的 uri,不是它说明栏目跳到了别的主题


FOX = "FOX Sports"
NATGEO = "National Geographic"
SOURCES: dict[str, Source] = {
    "foxsports-all": Source(FOX, "All Headlines", f"{FOX_RSS}&size=30", "https://www.foxsports.com/", "feed"),
    "foxsports-top": Source(
        FOX,
        "Top Headlines",
        f"{FOX_RSS}&aggregateId=7f83e8ca-6701-5ea0-96ee-072636b67336",
        "https://www.foxsports.com/",
        "feed",
    ),
    "foxsports-nba": Source(FOX, "NBA", f"{FOX_RSS}&size=30&tags=fs/nba", "https://www.foxsports.com/nba", "feed"),
    "foxsports-soccer": Source(FOX, "Soccer", f"{FOX_RSS}&size=30&tags={FOX_SOCCER_TAGS}", "https://www.foxsports.com/soccer", "feed"),
    "foxsports-tennis": Source(
        FOX,
        "Tennis",
        "https://www.foxsports.com/tennis",
        "https://www.foxsports.com/tennis/atp",
        "fox-page",
        list_uri="tennis/atp/league/2",
    ),
    "foxsports-olympics": Source(
        FOX,
        "Olympics",
        "https://www.foxsports.com/olympics",
        "https://www.foxsports.com/winter-olympics",
        "fox-page",
        list_uri="olympics/winter/league/2",
    ),
    "apple-service-programs": Source(
        "Apple 支持",
        "服务计划（更换和维修扩展计划）",
        "https://support.apple.com/service-programs",
        "https://support.apple.com/service-programs",
        "apple",
    ),
    "caranddriver-latest": Source(
        "Car and Driver", "Latest Content", "https://www.caranddriver.com/rss/all.xml/", "https://www.caranddriver.com/", "feed"
    ),
    "aeon-latest": Source("Aeon", "Ideas（essays / videos 最新）", "https://aeon.co/feed.rss", "https://aeon.co/", "feed"),
    "natgeo-photo-of-the-day": Source(
        NATGEO,
        "Photo of the Day",
        "https://www.nationalgeographic.com/photo-of-the-day",
        "https://www.nationalgeographic.com/photo-of-the-day",
        "natgeo-potd",
    ),
    "natgeo-latest": Source(
        NATGEO,
        "Latest Stories",
        "https://www.nationalgeographic.com/pages/topic/latest-stories",
        "https://www.nationalgeographic.com/pages/topic/latest-stories",
        "natgeo-latest",
    ),
    "newscientist-tech": Source(
        "New Scientist",
        "Technology",
        "https://www.newscientist.com/subject/technology/feed/",
        "https://www.newscientist.com/subject/technology/",
        "feed",
        ua=None,
    ),
    "newscientist-home": Source(
        "New Scientist",
        "首页最新",
        "https://www.newscientist.com/feed/home/",
        "https://www.newscientist.com/",
        "feed",
        ua=None,
    ),
    "hbr-latest": Source("Harvard Business Review", "Latest", "http://feeds.hbr.org/harvardbusiness", "https://hbr.org/", "hbr"),
    "sciam-latest": Source(
        "Scientific American",
        "Latest",
        "https://www.scientificamerican.com/platform/syndication/rss/",
        "https://www.scientificamerican.com/",
        "feed",
    ),
    "sciencenews-latest": Source("Science News", "Latest", "https://www.sciencenews.org/feed", "https://www.sciencenews.org/", "feed"),
}

# 声明序第一个是默认榜(board_api DEFAULT_TYPE=foxsports-top)。
type_map: dict[str, str] = {
    "foxsports-top": "FOX Sports · Top Headlines",
    "foxsports-all": "FOX Sports · All Headlines",
    "foxsports-nba": "FOX Sports · NBA",
    "foxsports-soccer": "FOX Sports · Soccer",
    "foxsports-tennis": "FOX Sports · Tennis",
    "foxsports-olympics": "FOX Sports · Olympics",
    "apple-service-programs": "Apple 支持 · 服务计划（更换和维修扩展计划）",
    "caranddriver-latest": "Car and Driver · Latest Content",
    "aeon-latest": "Aeon · Ideas（essays / videos 最新）",
    "natgeo-photo-of-the-day": "National Geographic · Photo of the Day",
    "natgeo-latest": "National Geographic · Latest Stories",
    "newscientist-tech": "New Scientist · Technology",
    "newscientist-home": "New Scientist · 首页最新",
    "hbr-latest": "Harvard Business Review · Latest",
    "sciam-latest": "Scientific American · Latest",
    "sciencenews-latest": "Science News · Latest",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "英文科学、体育与综合媒体 feed",
    "description": (
        "FOX Sports、Apple 支持服务计划、Car and Driver、Aeon、国家地理、New Scientist、"
        "HBR、Scientific American、Science News 的官方 feed 与栏目页"
    ),
    "link": "https://www.foxsports.com/rss-feeds",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}


# ---------------------------------------------------------------- 请求


async def _fetch_source(src: Source, no_cache: bool, cache_key: str) -> RequestResult:
    headers = {"Accept": FEED_ACCEPT if src.parser in ("feed", "hbr") else HTML_ACCEPT}
    if src.ua:
        headers["User-Agent"] = src.ua
    try:
        return await get(url=src.url, headers=headers, no_cache=no_cache, response_type="text", cache_key=cache_key)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 406:
            # New Scientist 对冒充浏览器的请求返回 406 空响应;UA 必须是程序 UA
            raise RuntimeError(
                f"{src.site} returned 406 with an empty body: it rejects browser-impersonating "
                "requests, keep the default program UA (python-httpx)"
            ) from exc
        raise


# ---------------------------------------------------------------- 通用小工具


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_html(value: Any, limit: int = 500) -> str | None:
    text = _text(BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True))
    return text[:limit] or None


def _attr(tag: Tag | None, name: str) -> str:
    value = tag.get(name) if tag is not None else None
    return value.strip() if isinstance(value, str) else ""


def _child_text(node: Tag, name: str) -> str:
    child = node.find(name)
    return _text(child.get_text(" ", strip=True)) if isinstance(child, Tag) else ""


def _iso_ms(value: str) -> int | None:
    """"2026-09-27T18:35:17Z" 等 ISO 时刻 → 毫秒。"""
    try:
        seconds = int(datetime.fromisoformat(value.strip()).timestamp())
    except ValueError:
        return None
    return get_time(seconds)


def _us_date_ms(value: str) -> int | None:
    """"June 13, 2025" → 当天 00:00 UTC 的毫秒(页面只给日期,时区不明按 UTC)。"""
    matched = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})", value or "")
    if not matched:
        return None
    try:
        moment = datetime.strptime(
            f"{matched.group(1)} {matched.group(2)} {matched.group(3)}", "%B %d %Y"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None
    return get_time(int(moment.timestamp()))


# ---------------------------------------------------------------- 解析:HBR Atom


def parse_hbr(xml: str) -> list[ListItem]:
    """HBR 的 Atom:标签带 ns6: 前缀、link 是相对路径(按 feed 声明的 http://hbr.org 补全,
    与 tophub 同形);作者可能多个用逗号连;配图在自定义 thumbnail-image-uri;保留 feed 原顺序。"""
    soup = BeautifulSoup(xml, "xml")
    feed = soup.find("feed")
    base = "http://hbr.org"
    if isinstance(feed, Tag):
        alternate = feed.find("link", attrs={"rel": "alternate"}, recursive=False)
        base = _attr(alternate if isinstance(alternate, Tag) else None, "href") or base
    items: list[ListItem] = []
    for entry in soup.find_all("entry"):
        if not isinstance(entry, Tag):
            continue
        title = _child_text(entry, "title")
        link = entry.find("link")
        url = urljoin(base.rstrip("/") + "/", _attr(link if isinstance(link, Tag) else None, "href"))
        if not title or not url.startswith(("http://", "https://")):
            continue
        authors = [_text(a.get_text(" ", strip=True)) for a in entry.select("author > name")]
        cover = _child_text(entry, "thumbnail-image-uri")
        published = _child_text(entry, "published") or _child_text(entry, "updated")
        items.append(
            ListItem(
                id=_child_text(entry, "id") or url,
                title=title,
                url=url,
                mobileUrl=url,
                author=", ".join(author for author in authors if author) or None,
                cover=cover if cover.startswith(("http://", "https://")) else None,
                desc=_clean_html(_child_text(entry, "summary")),
                timestamp=_iso_ms(published) if published else None,
            )
        )
    return items


# ---------------------------------------------------------------- 解析:Apple 服务计划


def parse_apple(html: str, page: str) -> list[ListItem]:
    """每个计划一个 section.as-container-column:左栏产品图,右栏计划链接 +
    span.note 里的日期(如 "June 13, 2025")。id 用计划页路径(如 /beats-pillxl-recall)。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for section in soup.select("section.as-container-column"):
        anchor = section.select_one(".as-richtext a[href]")
        href = _attr(anchor, "href")
        if anchor is None or not href:
            continue
        url = urljoin(page, href)
        title = _text(anchor.get_text(" ", strip=True))
        if not title or url in seen:
            continue
        seen.add(url)
        note = section.select_one("span.note")
        image = _attr(section.select_one("img[src]"), "src")
        items.append(
            ListItem(
                id=urlsplit(url).path or url,
                title=title,
                url=url,
                mobileUrl=url,
                cover=urljoin(page, image) if image else None,
                timestamp=_us_date_ms(note.get_text(" ", strip=True)) if note else None,
            )
        )
    return items


# ---------------------------------------------------------------- 解析:国家地理 window['__natgeo__']


def natgeo_state(html: str) -> dict[str, Any]:
    matched = re.search(r"window\['__natgeo__'\]\s*=\s*", html)
    if not matched:
        raise RuntimeError("NatGeo page has no window['__natgeo__'] (page structure changed)")
    state, _ = json.JSONDecoder().raw_decode(html, matched.end())
    if not isinstance(state, dict):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            "NatGeo window['__natgeo__'] is not an object"
        )
    return state


def _mods(section: Any) -> list[dict[str, Any]]:
    """page.content.<区块>.frms[].mods[] 展平成一个列表(页面模块顺序)。"""
    out: list[dict[str, Any]] = []
    for frame in (section or {}).get("frms") or []:
        for mod in (frame or {}).get("mods") or []:
            if isinstance(mod, dict):
                out.append(mod)
    return out


def _cursor_ms(cursor: str) -> int | None:
    """媒体条目 cursor 是分页游标:点号前一段 base64 解出来形如
    "...#SORT:originalPublishedDate|1790334000000"(毫秒)。"""
    head = (cursor or "").split(".")[0]
    try:
        raw = base64.b64decode(head + "=" * (-len(head) % 4)).decode("utf-8", "replace")
    except ValueError:
        return None
    matched = re.search(r"originalPublishedDate\|(\d{12,13})", raw)
    return int(matched.group(1)) if matched else None


def parse_natgeo_potd(html: str) -> list[ListItem]:
    """每日一图画廊:mediaspotlight 的 edgs[].media[](服务端给 10 张,新的在前)。
    标题用图注标题("September 25, 2026 | Before the Sun Rises",与 tophub 同形),
    日期从 cursor 解出,解不出时从图注标题的日期取;周末不更新。"""
    state = natgeo_state(html)
    spotlight = ((state.get("page") or {}).get("content") or {}).get("mediaspotlight") or {}
    items: list[ListItem] = []
    for mod in _mods(spotlight):
        for edge in mod.get("edgs") or []:
            for media in (edge or {}).get("media") or []:
                if not isinstance(media, dict) or not media.get("locator"):
                    continue
                image = media.get("img") or {}
                caption = media.get("caption") or {}
                title = _text(caption.get("title") or image.get("ttl"))
                url = urljoin(NATGEO_BASE, str(media["locator"]))
                if not title:
                    continue
                items.append(
                    ListItem(
                        id=str(media.get("slug") or url),
                        title=title,
                        url=url,
                        mobileUrl=url,
                        cover=image.get("src") or image.get("rt"),
                        author=_text(image.get("crdt")) or None,
                        desc=_clean_html(caption.get("text") or image.get("dsc")),
                        timestamp=_cursor_ms(str(media.get("cursor") or "")) or _us_date_ms(title),
                    )
                )
    return items


def parse_natgeo_latest(html: str) -> list[ListItem]:
    """"最新故事"页:hub.frms[].mods[] 里带 tiles 的模块,按页面顺序(PromoGridModule 5 条 +
    InfiniteFeedModule 10 条)。tile 没有日期字段,timestamp 留空;列表按
    originalPublishedDate 倒序出(分页游标里是这个排序键),照页面顺序输出不重排。"""
    state = natgeo_state(html)
    hub = ((state.get("page") or {}).get("content") or {}).get("hub") or {}
    items: list[ListItem] = []
    seen: set[str] = set()
    for mod in _mods(hub):
        for tile in mod.get("tiles") or []:
            if not isinstance(tile, dict):
                continue
            ctas = tile.get("ctas") or []
            url = str((ctas[0] or {}).get("url") or "") if ctas and isinstance(ctas[0], dict) else ""
            title = _text(tile.get("title"))
            if not title or not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            image = tile.get("img") or {}
            items.append(
                ListItem(
                    id=str(tile.get("storyId") or tile.get("id") or url),
                    title=title,
                    url=url,
                    mobileUrl=url,
                    cover=image.get("src") or image.get("rt"),
                    desc=_clean_html(tile.get("description") or tile.get("abstract")),
                )
            )
    return items


# ---------------------------------------------------------------- 解析:FOX Sports 栏目页 __NUXT_DATA__


FOX_BASE = "https://www.foxsports.com"
# Nuxt payload(devalue 格式)里的负数引用
_DEVALUE_CONST: dict[int, Any] = {-1: None, -2: None, -3: float("nan"), -4: float("inf"), -5: float("-inf"), -6: 0}


def nuxt_payload(html: str) -> Any:
    """解开 <script id="__NUXT_DATA__"> 的 devalue 扁平数组:数组 / 对象里的整数是下标引用;
    首元素是字符串的数组是带类型的值(Date、Set、Map,以及 Nuxt 的 Reactive / Ref /
    ShallowReactive 等包装)。"""
    matched = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not matched:
        raise RuntimeError("FOX Sports page has no __NUXT_DATA__ (page structure changed)")
    flat = json.loads(matched.group(1))
    if not isinstance(flat, list) or not flat:
        raise RuntimeError("FOX Sports __NUXT_DATA__ is not a devalue array")
    memo: dict[int, Any] = {}

    def hydrate(index: Any) -> Any:
        if not isinstance(index, int) or isinstance(index, bool):
            return index
        if index < 0:
            return _DEVALUE_CONST.get(index)
        if index in memo:
            return memo[index]
        value = flat[index]
        if isinstance(value, dict):
            obj: dict[str, Any] = {}
            memo[index] = obj
            obj.update((key, hydrate(item)) for key, item in value.items())
            return obj
        if not isinstance(value, list):
            return value
        if value and isinstance(value[0], str):  # 带类型的值
            kind = value[0]
            if kind in ("Date", "RegExp", "BigInt"):
                out: Any = value[1] if len(value) > 1 else None
            elif kind == "Set":
                out = [hydrate(item) for item in value[1:]]
            elif kind in ("Map", "null"):
                out = {str(hydrate(value[item])): hydrate(value[item + 1]) for item in range(1, len(value) - 1, 2)}
            else:  # Object / Reactive / ShallowReactive / Ref / ShallowRef / EmptyRef …:取被包装的值
                out = hydrate(value[1]) if len(value) > 1 else None
            memo[index] = out
            return out
        arr: list[Any] = []
        memo[index] = arr
        arr.extend(hydrate(item) for item in value)
        return arr

    return hydrate(0)


def fox_page_list(html: str) -> dict[str, Any]:
    """栏目页"NEWS"标签下的新闻列表:payload.data 里 league-page 的
    secondaryNavigationViewModel.content.apiEndpointResponseData。
    它就是页面上那 25 张卡片(服务端渲染,顺序相同),下面是分页(?p=2…)。"""
    data = (nuxt_payload(html) or {}).get("data") or {}
    for value in data.values() if isinstance(data, dict) else []:
        content = (
            (((value or {}).get("secondaryNavigationViewModel") or {}).get("content") or {})
            if isinstance(value, dict)
            else {}
        )
        api = content.get("apiEndpointResponseData") if isinstance(content, dict) else None
        if isinstance(api, dict) and isinstance((api.get("data") or {}).get("results"), list):
            return api
    raise RuntimeError("FOX Sports page has no apiEndpointResponseData.data.results (page structure changed)")


def _fox_url(row: dict[str, Any]) -> str:
    """canonical_url:外站稿是完整地址;FOX 自己的稿(AP 通稿、FOX 原创、视频)写成
    "foxsports.com/articles/…",页面上的链接是 /articles/…,补成 https://www.foxsports.com/…。"""
    urls = row.get("urls") if isinstance(row.get("urls"), dict) else {}
    for candidate in (row.get("canonical_url"), (urls or {}).get("url"), (urls or {}).get("original_url")):
        url = str(candidate or "").strip()
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("foxsports.com/"):
            return "https://www." + url
        if url.startswith("/"):
            return FOX_BASE + url
    return ""


def parse_fox_page(html: str, list_uri: str | None) -> list[ListItem]:
    """每条:title、canonical_url、dek(摘要)、thumbnail.url、last_published_date(列表按它倒序)。
    author 取卡片上时间后面显示的来源(external_source:Associated Press、si.com 等),
    没有时用署名。列表里除了 FOX / AP 的稿,还有 Newswhip 按关键词聚合来的外站链接
    (content_type=external_newswhip),页面上照样展示,一并保留。"""
    api = fox_page_list(html)
    params = str(((api.get("data") or {}).get("request") or {}).get("params") or "")
    uri = str(api.get("contentUri") or "")
    if list_uri and uri != list_uri:
        raise RuntimeError(
            f"FOX Sports column page list is {uri or '(empty)'} ({params}), expected {list_uri}: "
            "the column may have moved to another topic"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in api["data"]["results"]:
        if not isinstance(row, dict):
            continue
        title = _text(htmllib.unescape(str(row.get("title") or "")))
        url = _fox_url(row)
        if not title or not url or url in seen:
            continue
        seen.add(url)
        thumbnail = row.get("thumbnail") if isinstance(row.get("thumbnail"), dict) else {}
        cover = str((thumbnail or {}).get("url") or "")
        names = [_text(author.get("name")) for author in row.get("authors") or [] if isinstance(author, dict)]
        published = str(row.get("last_published_date") or row.get("original_import_date") or "")
        items.append(
            ListItem(
                id=str(row.get("id") or row.get("spark_id") or url),
                title=title,
                url=url,
                mobileUrl=url,
                author=_text(row.get("external_source")) or ", ".join(name for name in names if name) or None,
                cover=cover if cover.startswith(("http://", "https://")) else None,
                desc=_clean_html(row.get("dek")),
                timestamp=_iso_ms(published) if published else None,
            )
        )
    return items


# ---------------------------------------------------------------- 入口


def _parse_items(src: Source, body: Any) -> list[ListItem]:
    if src.parser == "feed":
        return parse_feed(str(body))
    if src.parser == "hbr":
        return parse_hbr(str(body))
    if src.parser == "apple":
        return parse_apple(str(body), src.page)
    if src.parser == "natgeo-potd":
        return parse_natgeo_potd(str(body))
    if src.parser == "natgeo-latest":
        return parse_natgeo_latest(str(body))
    return parse_fox_page(str(body), src.list_uri)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in type_map:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")
    src = SOURCES[selected]
    result = await _fetch_source(src, no_cache, cache_key=f"{ROUTE_NAME}:{selected}")
    items = _parse_items(src, result.data)
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"{src.site} · {src.column} parsed no items from {src.url}")
    return RouterData(
        **{**ROUTE_META, "link": src.page},
        type=type_map[selected],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
