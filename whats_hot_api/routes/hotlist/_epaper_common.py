"""电子报公共解析(epaper-central 与 epaper-local 两个路由共用)。

口径照 board_api 证据(tmp/board_api/epaper_central、tmp/board_api/epaper_local,
2026-09-28 冷启动留档):每个子榜是一份报纸(或期刊)当期(最近一期)全部版面的文章,
按版面顺序、版内文章顺序输出;url 是文章页,desc 是"第 N 版 版名",timestamp 是出版
日期的北京时间 0 点(毫秒)。当天没有出版(周末、节假日)或还没上传时取最近一期,
message 写明期数日期。

国内报社电子报大多是方正的几套系统,通用解析写在这里:
- 系统 A(方正新版 amucsite):layout/index.html 列出当期各版 → YYYYMM/DD/node_XX.html
  (每版一页)→ 本版文章 content/YYYYMM/DD/content_N.html
- 系统 A 变体(#webtree):首版 node 页一页列出全期每一版(dt 版名 + dd 本版文章),2 个请求
- 系统 B(方正经典):入口 meta refresh 跳到当期首版 html/YYYY-MM/DD/node_N.htm →
  首版页的版面导航列出全部版 → 逐版取本版文章 content_N.htm
- 系统 C(PaperIndex):content/PaperIndex.htm → YYYYMMDD/IssueIndex.htm → PageNNXX.htm
  → 文章 ArticelNNNNNXX.htm;新华每日电讯首版页 div.listdaohang 一页列出全期
各报专用入口与专用解析写在各自路由模块。

反爬口径(board_api verify/header_matrix.jsonl):全部请求带浏览器 UA——解放军报
newestPaper 对 python-httpx UA 返回 403,北京日报 paperindex 不带 UA 返回 403,
21世纪经济报道首页对 python-httpx UA 返回 404;科技日报 uv 接口另带页面 axios 实例的
x-requested-with: XMLHttpRequest,否则返回 {"status":"500","msg":"no access!"}。
同站限速照 board_api common.throttle 口径:同一站点两次请求至少隔 1.2 秒。

未移植:epaper_local 大众报业(paper.dzwww.com)"连接失败改连备用节点 IP"的回退
(board_api DZWWW_PINS)——Core 共享 http_client 不做进程级 DNS pin,连接失败直接抛错,
由调用方/调度器稍后重试;编码一律按响应头(httpx),这些站点的响应头都是 UTF-8 或不带
charset(httpx 缺省 UTF-8),页面 meta 误标 gb2312 的两站(中国科学报、北京日报)不受影响。
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from whats_hot_api.models import ListItem
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

CHINA_TZ = timezone(timedelta(hours=8))

# 全部请求带浏览器 UA(board_api 证据:3 个站点对 httpx 缺省 UA 报 403/404)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_JSON_HEADERS = {
    **_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# 同一站点两次请求的最小间隔(board_api common.throttle 口径);测试置 0
_MIN_SITE_GAP_SECONDS = 1.2

# 不算条目的标题:整条只有"广告"两个字的是广告位(每经 04 版),不是文章
_SKIP_TITLES = {"广告"}


# ---------------------------------------------------------------- 数据结构


@dataclass
class Article:
    title: str
    url: str
    id: str | None = None
    author: str | None = None


@dataclass
class PaperPage:
    """一个版面(或期刊栏目)。label 是版号("01"、"A01"),没有版号时为空。"""

    label: str
    name: str
    articles: list[Article] = field(default_factory=list)

    def desc(self) -> str | None:
        if self.label:
            return f"第{self.label}版 {self.name}".strip()
        return self.name or None


@dataclass
class Issue:
    date: date | None  # 出版日期;期刊没有单一的出版日期时为空
    pages: list[PaperPage]
    name: str = ""  # 期号,如"第1290期""2026年第4期"
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 文本工具


def clean_text(text: str | None) -> str:
    """合并空白(含全角空格、不换行空格),去掉首尾空白。"""
    return re.sub(r"[\s\u200b]+", " ", text or "").strip()


def tag_text(tag: Any) -> str:
    return clean_text(tag.get_text(" ")) if isinstance(tag, Tag) else ""


def attr_of(tag: Any, name: str) -> str:
    value = tag.get(name) if isinstance(tag, Tag) else None
    if isinstance(value, list):
        value = " ".join(value)
    return str(value or "").strip()


def strip_html(fragment: str | None) -> str:
    """去掉标题里的 HTML(如 <p>、<br/>),<br> 换成空格。"""
    text = re.sub(r"<br\s*/?>", " ", fragment or "", flags=re.IGNORECASE)
    if "<" in text or "&" in text:
        return clean_text(BeautifulSoup(text, "lxml").get_text(" "))
    return clean_text(text)


_LABEL = re.compile(r"^[(（]?\s*第?\s*([A-Za-z]{0,3}\d+)\s*(?:版|[)）])\s*[：:]?\s*(.*)$")


def norm_label(label: str) -> str:
    """版号统一:"00001" → "01";其余照原样("A01"、"0607" 合版、"GA01")。"""
    label = clean_text(label)
    m = re.fullmatch(r"0+(\d{2})", label)
    return m.group(1) if m else label


def parse_label(text: str) -> tuple[str, str] | None:
    """"第01版 要闻"/"01版：要闻"/"(GA01) 封面" → ("01", "要闻");不是版面名的文字返回 None。"""
    m = _LABEL.match(clean_text(text))
    if not m:
        return None
    return norm_label(m.group(1)), clean_text(m.group(2))


def page_number(label: str) -> int | None:
    m = re.search(r"(\d+)$", label)
    return int(m.group(1)) if m else None


def no_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def dedup_key(url: str) -> str:
    """去重键:去掉协议(http/https 算同一篇);查询串与锚点保留(接口拼出来的文章靠它们区分)。"""
    p = urlsplit(url)
    return urlunsplit(("", p.netloc, p.path, p.query, p.fragment))


def day_start_ms(d: date) -> int | None:
    """出版日期的北京时间 0 点,Unix 毫秒。"""
    if d is None:
        return None
    return get_time(f"{d:%Y-%m-%d}")


def beijing_today() -> date:
    return datetime.now(CHINA_TZ).date()


# ---------------------------------------------------------------- 请求端口

_META_REFRESH = re.compile(
    r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]*content=[\"']?\s*\d+\s*;\s*url=([^\"'>\s]+)",
    re.IGNORECASE,
)
_JS_LOCATION = re.compile(r"(?:window\.)?location(?:\.href)?\s*=\s*[\"']([^\"']+)[\"']")


class EpaperFetch:
    """一次抓取的请求端口:统一请求头、同站限速,并记录最后一次请求的缓存状态。

    全部请求走共享 get/post(测试 patch 本模块的 get/post);共享 http_client 跟随
    HTTP 302,这里只再处理 meta refresh / JS location 跳转(follow)。
    """

    def __init__(self, no_cache: bool = False) -> None:
        self.no_cache = no_cache
        self.from_cache = False
        self.update_time = ""
        self.notes: list[str] = []
        self._last_at: dict[str, float] = {}

    def _record(self, result: Any) -> None:
        self.from_cache = bool(getattr(result, "from_cache", False))
        update_time = getattr(result, "update_time", "")
        if update_time:
            self.update_time = update_time

    async def _pace(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        last = self._last_at.get(host)
        wait = 0.0
        if last is not None:
            wait = _MIN_SITE_GAP_SECONDS - (time.monotonic() - last)
        self._last_at[host] = time.monotonic() + max(wait, 0.0)
        if wait > 0:
            await asyncio.sleep(wait)

    async def page(self, url: str) -> tuple[str, str]:
        """GET 一个 HTML 页面,返回 (请求地址, 文本);非 2xx 由共享 http_client 抛错。

        返回的是请求地址:这些站点里只有浙江日报入口有 HTTP 302,该入口直接改用
        302 落地页(zjrb.zjol.com.cn),其余页面请求地址即页面地址,可直接做 urljoin 基准。
        """
        await self._pace(url)
        result = await get(url=url, headers=_HEADERS, no_cache=self.no_cache, response_type="text")
        self._record(result)
        return url, str(result.data or "")

    async def json(self, url: str) -> Any:
        await self._pace(url)
        result = await get(url=url, headers=_JSON_HEADERS, no_cache=self.no_cache, response_type="json")
        self._record(result)
        return result.data

    async def post_json(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        await self._pace(url)
        result = await post(
            url=url,
            headers={**_HEADERS, **(headers or {})},
            body=body,
            no_cache=self.no_cache,
            response_type="json",
        )
        self._record(result)
        return result.data

    async def follow(self, url: str, until: re.Pattern[str], hops: int = 6) -> tuple[str, str]:
        """顺着 meta refresh / JS location 跳转,直到地址匹配 until(电子报入口常用它跳当期首版)。"""
        text = ""
        for _ in range(hops):
            url, text = await self.page(url)
            if until.search(no_query(url)):
                return url, text
            m = _META_REFRESH.search(text) or _JS_LOCATION.search(text)
            if not m:
                break
            url = urljoin(url, m.group(1).strip())
        raise RuntimeError(f"入口没有跳到当期版面页:停在 {url}")


# ---------------------------------------------------------------- 版面文章列表

_NODE_A = re.compile(r"(\d{6})/(\d{2})/node_([A-Za-z]*\d+)\.html?$")
_CONTENT_A = re.compile(r"content_\d+\.html?")
_NODE_B = re.compile(r"/html/(\d{4})-(\d{2})/(\d{2})/node_\d+\.htm$")
_CONTENT_B = re.compile(r"content_\d+(?:_\d+)?\.htm")
_PAGE_C = re.compile(r"/content/(\d{4})(\d{2})(\d{2})/Page\w+\.htm$")
_ARTICLE_C = re.compile(r"Articel\w+\.htm")


def _articles_in(soup: BeautifulSoup, base: str, pattern: re.Pattern[str], date_dir: str) -> list[Article]:
    """页面里指向同一期文章页、带文字的链接(版面图热区 <area> 没有文字,不算)。
    按页面出现顺序,同一链接只留第一次。"""
    out: list[Article] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = attr_of(a, "href")
        if not pattern.search(href):
            continue
        url = urljoin(base, href)
        if date_dir not in url:
            continue
        title = tag_text(a)
        key = dedup_key(url)
        if not title or key in seen:
            continue
        seen.add(key)
        out.append(Article(title=title, url=url))
    return out


# ---------------------------------------------------------------- 系统 A:方正新版


async def fangzheng_a(f: EpaperFetch, index_url: str) -> Issue:
    """layout/index.html 列出当期各版(版号 + 版名),逐版请求 node 页取本版文章列表。"""
    base, text = await f.page(index_url)
    soup = BeautifulSoup(text, "lxml")
    nodes: list[tuple[str, str, str]] = []
    for a in soup.find_all("a"):
        url = urljoin(base, attr_of(a, "href"))
        if not _NODE_A.search(no_query(url)):
            continue
        parsed = parse_label(tag_text(a))
        if parsed and url not in [n[0] for n in nodes]:
            nodes.append((url, *parsed))
    if not nodes:
        raise RuntimeError(f"版面目录没有解析到版面:{index_url}")
    m = _NODE_A.search(nodes[0][0])
    assert m
    issue_date = date(int(m.group(1)[:4]), int(m.group(1)[4:]), int(m.group(2)))
    date_dir = f"{m.group(1)}/{m.group(2)}/"
    pages: list[PaperPage] = []
    for url, label, name in nodes:
        page_url, page_text = await f.page(url)
        arts = _articles_in(BeautifulSoup(page_text, "lxml"), page_url, _CONTENT_A, date_dir)
        pages.append(PaperPage(label, name, arts))
    return Issue(issue_date, pages)


async def fangzheng_a_tree(f: EpaperFetch, index_url: str) -> Issue:
    """系统 A 变体(证券时报):首版 node 页的 #webtree 一页列出全期每一版,只需两个请求。"""
    base, text = await f.page(index_url)
    m = _NODE_A.search(no_query(base))
    if not m:
        first = None
        for a in BeautifulSoup(text, "lxml").find_all("a"):
            if _NODE_A.search(no_query(attr_of(a, "href"))):
                first = urljoin(base, attr_of(a, "href"))
                break
        if not first:
            raise RuntimeError(f"版面目录没有解析到版面:{index_url}")
        base, text = await f.page(first)
        m = _NODE_A.search(no_query(base))
    assert m
    issue_date = date(int(m.group(1)[:4]), int(m.group(1)[4:]), int(m.group(2)))
    date_dir = f"{m.group(1)}/{m.group(2)}/"
    soup = BeautifulSoup(text, "lxml")
    tree = soup.select_one("#webtree")
    if tree is None:
        raise RuntimeError(f"版面页没有 #webtree:{base}")
    pages: list[PaperPage] = []
    for dl in tree.find_all("dl"):
        dt = dl.find("dt")
        parsed = parse_label(tag_text(dt)) if dt else None
        if not parsed:
            continue
        dd = dl.find("dd")
        arts = _articles_in(BeautifulSoup(str(dd), "lxml"), base, _CONTENT_A, date_dir) if dd else []
        pages.append(PaperPage(parsed[0], parsed[1], arts))
    return Issue(issue_date, pages)


# ---------------------------------------------------------------- 系统 B:方正经典


async def fangzheng_b(f: EpaperFetch, entry_url: str) -> Issue:
    """入口 meta refresh 到当期首版;首版页的版面导航列出全部版,逐版请求取 content_N.htm。"""
    url, text = await f.follow(entry_url, _NODE_B)
    m = _NODE_B.search(no_query(url))
    assert m
    issue_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    date_dir = f"{m.group(1)}-{m.group(2)}/{m.group(3)}/"
    soup = BeautifulSoup(text, "lxml")
    nav: list[tuple[str, str, str]] = []
    for a in soup.find_all("a"):
        href = attr_of(a, "href")
        if not re.search(r"node_\d+\.htm", href):
            continue
        parsed = parse_label(tag_text(a))
        node = no_query(urljoin(url, href))
        if not parsed or date_dir not in node or node in [n[0] for n in nav]:
            continue
        nav.append((node, *parsed))
    if not nav:
        raise RuntimeError(f"首版页没有解析到版面导航:{url}")
    pages: list[PaperPage] = []
    for node, label, name in nav:
        if node == no_query(url):
            page_url, page_soup = url, soup
        else:
            page_url, page_text = await f.page(node)
            page_soup = BeautifulSoup(page_text, "lxml")
        pages.append(PaperPage(label, name, _articles_in(page_soup, page_url, _CONTENT_B, date_dir)))
    return Issue(issue_date, pages)


# ---------------------------------------------------------------- 系统 C:PaperIndex


def _page_nav_c(soup: BeautifulSoup, base: str) -> list[tuple[str, str, str]]:
    """版面导航:同一个 Page 链接可能出现多次("下一版"),按链接合并文字;
    顺序取该链接第一次以版号/版名形式出现的位置("下一版"不算,否则第 2 版会排到第 1 版前)。"""
    texts: dict[str, list[str]] = {}
    order: list[str] = []
    for a in soup.find_all("a"):
        href = attr_of(a, "href")
        if not re.fullmatch(r"(?:\./)?Page\w+\.htm", href) or "ArticleIndex" in href:
            continue
        url = urljoin(base, href)
        text = tag_text(a)
        texts.setdefault(url, []).append(text)
        if url not in order and (parse_label(text) or re.fullmatch(r"[A-Za-z]*\d+", text)):
            order.append(url)
    nav: list[tuple[str, str, str]] = []
    for url in order:
        values = [v for v in texts[url] if v]
        parsed = next((p for p in map(parse_label, values) if p), None)
        if parsed is None and values and re.fullmatch(r"[A-Za-z]*\d+", values[0]):
            name = next((v for v in values[1:] if not re.fullmatch(r"[A-Za-z]*\d+", v) and v != "下一版"), "")
            parsed = (norm_label(values[0]), name)
        if parsed:
            nav.append((url, *parsed))
    return nav


async def paperindex_c(f: EpaperFetch, entry_url: str) -> Issue:
    """入口两次 meta refresh 到当期首版 PageNNXX.htm;逐版请求,取 ArticelNNNNNXX.htm 链接。
    新华每日电讯的首版页 div.listdaohang 一页列出全期每一版的文章,直接用它,不再逐版请求。"""
    url, text = await f.follow(entry_url, _PAGE_C)
    m = _PAGE_C.search(no_query(url))
    assert m
    issue_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    date_dir = f"/content/{m.group(1)}{m.group(2)}{m.group(3)}/"
    soup = BeautifulSoup(text, "lxml")
    listing = soup.select_one("div.listdaohang")
    if listing is not None:
        pages: list[PaperPage] = []
        for el in listing.find_all(["h4", "ul"], recursive=False):
            if el.name == "h4":
                a = next((x for x in el.find_all("a") if re.search(r"Page\w+\.htm", attr_of(x, "href"))), None)
                parsed = parse_label(tag_text(a)) if a else None
                if parsed:
                    pages.append(PaperPage(parsed[0], parsed[1]))
            elif pages:
                for a in el.find_all("a"):
                    href = attr_of(a, "daoxiang") or attr_of(a, "href")
                    title = tag_text(a)
                    if title and re.search(r"Articel\w+\.htm", href):
                        pages[-1].articles.append(Article(title=title, url=urljoin(url, href)))
        if pages:
            return Issue(issue_date, pages)
    nav = _page_nav_c(soup, url)
    if not nav:
        raise RuntimeError(f"首版页没有解析到版面导航:{url}")
    pages = []
    for node, label, name in nav:
        if node == no_query(url):
            page_url, page_soup = url, soup
        else:
            page_url, page_text = await f.page(node)
            page_soup = BeautifulSoup(page_text, "lxml")
        pages.append(PaperPage(label, name, _articles_in(page_soup, page_url, _ARTICLE_C, date_dir)))
    return Issue(issue_date, pages)


# ---------------------------------------------------------------- 组装输出


def issue_to_items(issue: Issue) -> list[ListItem]:
    """按版面顺序、版内顺序展开成条目;同一篇(同一链接)只留第一次;没有标题的链接跳过。"""
    ts = day_start_ms(issue.date)
    items: list[ListItem] = []
    seen: set[str] = set()
    for page in issue.pages:
        desc = page.desc()
        for art in page.articles:
            key = art.id or dedup_key(art.url)
            if not art.title or art.title in _SKIP_TITLES or key in seen:
                continue
            seen.add(key)
            items.append(
                ListItem(
                    id=art.id or art.url,
                    title=art.title,
                    url=art.url,
                    mobileUrl=art.url,
                    author=art.author or None,
                    desc=desc,
                    timestamp=ts,
                )
            )
    return items


def issue_message(issue: Issue, today: date | None = None) -> str:
    """当期日期、版数;"今天还没有新一期"与"版面未出齐"照 board_api 口径写进 message。"""
    today = today or beijing_today()
    if issue.date:
        head = f"当期 {issue.date:%Y-%m-%d}" + (f"({issue.name})" if issue.name else "")
        if issue.date < today:
            head += f";今天({today:%Y-%m-%d})还没有新一期(未出版或未上传),这是最近一期"
    else:
        head = f"当期 {issue.name}" if issue.name else "当期"
    parts = [head, f"{len(issue.pages)} 个版面"]
    labelled = [p for p in issue.pages if p.label]
    if labelled and not any(page_number(p.label) == 1 for p in labelled):
        shown = "、".join(p.label for p in labelled[:3]) + ("等" if len(labelled) > 3 else "")
        parts.append(f"版面未出齐:目录里没有第 1 版(只有 {shown}),当期可能还在上传")
    parts.extend(issue.notes)
    return ";".join(parts)
