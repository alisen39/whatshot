"""技术博客与 newsletter feed(官方 RSS/Atom、dev.to Top 榜,以及多个站点栏目页;公开,不登录、无 cookie)。

board_api 单元 `tmp/board_api/tech_blog_feeds` 的 1:1 迁移,证据见该目录 README、
`analysis_report.md`、`verify/min_request.log`、`verify/selfcheck.md`。28 个子榜
(子榜键照 board_api;dev.to Week 是 board_api DEFAULT_TYPE,声明序第一):

- 官方 RSS / Atom 17 个(Substack、Medium、Jekyll、WordPress 等):保留 feed 原顺序,
  feed 给多少条输出多少条(下游用 limit 截断)。公共 parse_feed 在条目带时间时按时间
  新→旧稳定排序,与本单元各 feed 本身的新→旧顺序一致;JMLR 无日期,保持原顺序
- dev.to Top 4 个:周 / 月 / 年用公开接口 /api/articles?top=7|30|365(一页 30 条),
  "Infinity" 用页面同源接口 /stories/feed/infinity?page=1(一页 18 条);top=N 的前
  18 条与 stories 同榜逐条相同(page_vs_output.md)。top=1(既有 devto 路由)与
  top=7 只重合 1 条,不是同一个榜;desc 拼法与 devto 路由 _article_item 一致
- HTML / 页面内嵌数据 7 个:
  - anond 人気記事アーカイブ:ul.archives 按日分组,日记 id 就是日本时间发布时刻
  - Product Hunt 首页"Top Products Launching Today"Apollo SSR 区块(Ad 广告跳过);
    "今天"按美西时间换天,区块里给几条输出几条
  - Indie Hackers 首页 div.homepage > div.organic(社区帖默认热门列表);
    featured / newest / Build Board 不算
  - 数据库内核月报目录页:一页列出全部期数,新的在前;只有年月,timestamp 留空
  - JavaScript Weekly:先取 /rss/ 找最新期号(/issues/latest 返回 400),再取期刊页;
    span.mainlink 主文,p.name 带 tag-sponsor 的赞助内容跳过;条目日期即期刊日期,
    timestamp 留空,期号和日期写进 type
  - 遥感学报:先取按北京时间当月猜的期次页,以页面菜单"当期目录"链接为准(不一致再取
    一次);每篇"更新时间"不一定是发布日期,timestamp 留空
  - 阮一峰"科技爱好者周刊"栏目页:whatshot 既有 ruanyifeng-weekly 路由抓的是全博客
    atom.xml,本子榜照 board_api 证据改用周刊栏目页(全部期数,新的在前)。每期后面的
    "（N@YYYY.MM.DD）"被 Cloudflare 当成邮箱改写成 data-cfemail,按异或规则还原取日期
    (北京时间 0 点);第 261 期地址拼错为 weely-issue-261,故不按 weekly-issue 匹配

反爬口径(board_api 实测):阮一峰栏目页对 curl 缺省 UA 返回 403 Cloudflare 封禁页,
带浏览器 UA 正常;其余站点程序 UA 即可。anond.hatelabo.jp 本机 DNS 间歇污染属于本地
环境问题,Core 共享 http_client 走系统解析,不做 DoH 特判(生产环境 DNS 正常)。
5 个不做不迁的榜(Chip Huyen、两个旧 Google AI Blog、Microsoft AI Blog、Superlinear)
见 board_api README"不做的榜"。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "tech-blog-feeds"

_BEIJING = timezone(timedelta(hours=8))
_JST = timezone(timedelta(hours=9))
# 阮一峰栏目页被 Cloudflare 按 UA 封 curl(min_request.log:curl UA 403、Chrome UA 200)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_DEVTO = "DEV Community"
_DEVTO_API_URL = "https://dev.to/api/articles"
_DEVTO_STORIES_URL = "https://dev.to/stories/feed/infinity"

# 官方 RSS / Atom 子榜:子榜键 → feed 地址(feed 给多少条输出多少条)。
_FEED_BOARDS: dict[str, str] = {
    "normaltech": "https://www.normaltech.ai/feed",
    "webdev-articles": "https://web.dev/static/articles/feed.xml",
    "eugeneyan": "https://eugeneyan.com/rss/",
    "jmlr": "https://jmlr.org/jmlr.xml",
    "lennys-newsletter": "https://www.lennysnewsletter.com/feed",
    "lexfridman-podcast": "https://lexfridman.com/feed/podcast/",
    "duckdb-news": "https://duckdb.org/feed.xml",
    "carlini-writing": "https://nicholas.carlini.com/writing/feed.xml",
    "oreilly-radar": "https://www.oreilly.com/radar/feed/",
    # 旧站 semianalysis.com/feed/ 停在 2025-09-16,文章已迁到 Substack;官网链到 newsletter 子域
    "semianalysis": "https://newsletter.semianalysis.com/feed",
    "wolfram-writings": "https://writings.stephenwolfram.com/feed/",
    "medium-netflix-techblog": "https://medium.com/feed/@netflixtechblog",
    "medium-odsc": "https://medium.com/feed/@odsc",
    "wolfram-blog": "https://blog.wolfram.com/feed/",
    "iosdevweekly": "https://iosdevweekly.com/issues.rss",
    "stanford-crfm": "https://crfm.stanford.edu/feed.xml",
    "nodeweekly": "https://nodeweekly.com/rss/",
}

# dev.to 公开接口子榜:子榜键 → (top 天数, 栏目名);stories 子榜单独处理。
_DEVTO_API_BOARDS: dict[str, tuple[int, str]] = {
    "devto-top-week": (7, "Top · Week"),
    "devto-top-month": (30, "Top · Month"),
    "devto-top-year": (365, "Top · Year"),
}
_DEVTO_STORIES_BOARD = "devto-top-infinity"

# 声明序第一个是默认榜(board_api DEFAULT_TYPE=devto-top-week)。
type_map: dict[str, str] = {
    "devto-top-week": f"{_DEVTO} · Top · Week",
    "devto-top-month": f"{_DEVTO} · Top · Month",
    "devto-top-year": f"{_DEVTO} · Top · Year",
    "devto-top-infinity": f"{_DEVTO} · Top · Infinity",
    "ruanyifeng-weekly": "阮一峰的网络日志 · 科技爱好者周刊",
    "producthunt-today": "Product Hunt · Top Products Launching Today",
    "indiehackers-home": "Indie Hackers · 首页热门",
    "anond-popular": "はてな匿名ダイアリー · 人気記事アーカイブ",
    "mysql-monthly": "数据库内核月报 · 全部期刊",
    "jsweekly-latest": "JavaScript Weekly · 最新一期",
    "ygxb-latest": "遥感学报 · 当期目次",
    "normaltech": "AI as Normal Technology · 最新文章",
    "webdev-articles": "web.dev · Articles",
    "eugeneyan": "Eugene Yan · Writing",
    "jmlr": "JMLR · Latest papers",
    "lennys-newsletter": "Lenny's Newsletter · 最新文章",
    "lexfridman-podcast": "Lex Fridman Podcast · 全部节目",
    "duckdb-news": "DuckDB · News",
    "carlini-writing": "Nicholas Carlini · Writing",
    "oreilly-radar": "O'Reilly Radar · Radar",
    "semianalysis": "SemiAnalysis · Newsletter",
    "wolfram-writings": "Stephen Wolfram Writings · 最新文章",
    "medium-netflix-techblog": "Netflix Technology Blog · Medium",
    "medium-odsc": "ODSC - Open Data Science · Medium",
    "wolfram-blog": "Wolfram Blog · 最新文章",
    "iosdevweekly": "iOS Dev Weekly · Issues",
    "stanford-crfm": "Stanford CRFM · Blog",
    "nodeweekly": "Node Weekly · Issues",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "技术博客与 newsletter feed",
    "description": (
        "技术博客、newsletter、播客的官方 feed,dev.to Top 榜,以及 Product Hunt、"
        "Indie Hackers、anond、数据库内核月报、JavaScript Weekly、遥感学报、阮一峰周刊的栏目页"
    ),
    "link": "https://dev.to/top/week",
    "params": {
        "type": {
            "name": "站点-栏目",
            "type": type_map,
        },
    },
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _text(element: Tag | None) -> str:
    return _clean(element.get_text(" ", strip=True)) if element is not None else ""


def _attr(element: Tag | None, name: str) -> str:
    value = element.get(name) if element is not None else None
    return str(value).strip() if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    match = re.search(r"\d[\d,]*", str(value or ""))
    return int(match.group(0).replace(",", "")) if match else None


def _soup(page_html: str) -> BeautifulSoup:
    return BeautifulSoup(page_html, "lxml")


def _iso_seconds(value: Any) -> int | None:
    """ISO 8601(含 Z / 时区偏移)→ 秒;models 层统一 ×1000 归一化毫秒。"""
    try:
        # Python 3.11+ 的 fromisoformat 直接识别 "Z" 后缀
        return int(datetime.fromisoformat(str(value or "").strip()).timestamp())
    except ValueError:
        return None


def _zone_date_seconds(value: str, fmt: str, zone: timezone) -> int | None:
    """按固定格式与指定时区解析日期,返回秒(models 统一转毫秒);解析失败返回 None。"""
    try:
        return int(datetime.strptime(value.strip(), fmt).replace(tzinfo=zone).timestamp())
    except ValueError:
        return None


# ---------------------------------------------------------------- dev.to


def _devto_desc(description: str, tags: Any, comments: Any, minutes: Any) -> str | None:
    """与 whatshot devto 路由 _article_item 相同:摘要 · 标签：a、b · 评论：N · 阅读：N 分钟。"""
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    meta = []
    if tags:
        meta.append("标签：" + "、".join(str(tag) for tag in tags))
    if comments is not None:
        meta.append(f"评论：{comments}")
    if minutes is not None:
        meta.append(f"阅读：{minutes} 分钟")
    # 摘要只 strip 不折叠内部空白,与 whatshot devto 路由 _article_item 完全一致
    return " · ".join(part for part in [description.strip(), *meta] if part) or None


def _devto_api_item(row: dict) -> ListItem | None:
    """公开接口 /api/articles?top=N:字段与 whatshot devto 路由 _article_item 相同。"""
    if row.get("id") is None or not row.get("title") or not row.get("url"):
        return None
    url = str(row["url"]).strip()
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return ListItem(
        id=str(row["id"]),
        title=_clean(row["title"]),
        url=url,
        mobileUrl=url,
        author=user.get("username") or user.get("name"),
        desc=_devto_desc(
            str(row.get("description") or ""), row.get("tag_list"), row.get("comments_count"),
            row.get("reading_time_minutes"),
        ),
        cover=row.get("cover_image") or row.get("social_image"),
        hot=row.get("public_reactions_count"),
        timestamp=get_time(row.get("published_at")),
    )


def _devto_stories_item(row: dict) -> ListItem | None:
    """页面同源接口 /stories/feed/<周期>:字段名不同(path、main_image、reading_time、
    published_at_int 秒),接口没有摘要。"""
    if not isinstance(row, dict) or row.get("id") is None or not row.get("title"):
        return None
    url = str(row.get("url") or "").strip() or urljoin("https://dev.to/", str(row.get("path") or ""))
    if not url.startswith(("http://", "https://")):
        return None
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return ListItem(
        id=str(row["id"]),
        title=_clean(row["title"]),
        url=url,
        mobileUrl=url,
        author=user.get("username") or user.get("name"),
        desc=_devto_desc("", row.get("tag_list"), row.get("comments_count"), row.get("reading_time")),
        cover=row.get("main_image"),
        hot=row.get("public_reactions_count"),
        timestamp=get_time(row.get("published_at_int")),  # 接口给的就是秒
    )


# ---------------------------------------------------------------- anond 人気記事アーカイブ


def _anond_items(page_html: str) -> list[ListItem]:
    """ul.archives 按日分组(span.date)> ol > li > a[href=/YYYYMMDDhhmmss]。
    日记 id 就是日本时间的发布时刻;はてなブックマーク数是图片,没有文字,hot 留空。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for anchor in _soup(page_html).select("ul.archives ol > li > a[href]"):
        href = _attr(anchor, "href")
        match = re.fullmatch(r"/(\d{14})", href)
        if not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        url = urljoin("https://anond.hatelabo.jp/", href)
        items.append(
            ListItem(
                id=match.group(1),
                title=_text(anchor),  # 长标题页面自己截成"....."
                url=url,
                mobileUrl=url,
                timestamp=get_time(_zone_date_seconds(match.group(1), "%Y%m%d%H%M%S", _JST)),
            )
        )
    return items


# ---------------------------------------------------------------- Product Hunt


def _js_array_after(text: str, start: int) -> list[Any]:
    """从 start 处的 JS 数组字面量解出 JSON(Apollo SSR 数据里夹着 undefined,换成 null)。"""
    chunk = re.sub(r"(?<=[:\[,])undefined(?=[,\]}])", "null", text[start:start + 3_000_000])
    value, _ = json.JSONDecoder().raw_decode(chunk)
    return value if isinstance(value, list) else []


def _producthunt_items(page_html: str) -> list[ListItem]:
    """首页 Apollo SSR 数据里 title 为 "Top Products Launching Today" 的区块,
    items[] 里 __typename=Post 的是产品(Ad 是广告,跳过);服务端给几条输出几条。"""
    key = '"title":"Top Products Launching Today"'
    pos = page_html.find(key)
    if pos < 0:
        raise RuntimeError("Product Hunt homepage has no 'Top Products Launching Today' block (page changed)")
    arr_at = page_html.find('"items":[', pos)
    if arr_at < 0 or arr_at - pos > 5000:
        raise RuntimeError("Product Hunt 'Top Products Launching Today' block has no items array")
    items: list[ListItem] = []
    for row in _js_array_after(page_html, arr_at + len('"items":')):
        if not isinstance(row, dict) or row.get("__typename") != "Post" or not row.get("name"):
            continue
        product = row.get("product") if isinstance(row.get("product"), dict) else {}
        slug = product.get("slug")
        url = (
            f"https://www.producthunt.com/products/{slug}"
            if slug
            else f"https://www.producthunt.com/posts/{row.get('slug')}"
        )
        if not url.startswith("https://") or not url.rstrip("/").rsplit("/", 1)[-1]:
            continue
        thumb = row.get("thumbnailImageUuid")
        items.append(
            ListItem(
                id=str(row.get("id") or url),
                title=_clean(row["name"]),
                url=url,
                mobileUrl=url,
                desc=_clean(row.get("tagline")) or None,
                cover=f"https://ph-files.imgix.net/{thumb}" if thumb else None,
                hot=row.get("latestScore"),
                timestamp=get_time(_iso_seconds(row.get("featuredAt") or row.get("createdAt"))),
            )
        )
    return items


# ---------------------------------------------------------------- Indie Hackers


def _indiehackers_items(page_html: str) -> list[ListItem]:
    """首页 div.homepage 下第一个列表 div.organic(社区帖按热度排的默认列表)。
    旁边的 div.featured(编辑部 spotlight)、div.newest、div.build-board / throwbacks 都不算。"""
    box = _soup(page_html).select_one("div.homepage > div.organic")
    if box is None:
        raise RuntimeError("Indie Hackers homepage has no div.organic list (page changed)")
    items: list[ListItem] = []
    seen: set[str] = set()
    for story in box.select("div.story"):
        anchor = story.select_one("a.story__text-link")
        title_tag = story.select_one(".story__title")
        href = _attr(anchor, "href")
        if anchor is None or not href or title_tag is None:
            continue
        url = urljoin("https://www.indiehackers.com/", href)
        if url in seen:
            continue
        seen.add(url)
        split = urlsplit(url)
        # 帖子 id 是链接末段;产品帖是 /product/<slug>?post=<id> 形态,取 ?post=
        post_id = (parse_qs(split.query).get("post") or [""])[0] or split.path.rstrip("/").rsplit("-", 1)[-1]
        items.append(
            ListItem(
                id=post_id or url,
                title=_text(title_tag),
                url=url,
                mobileUrl=url,
                author=_text(story.select_one(".user-link__name")) or None,
                hot=_int(_text(story.select_one(".story__count--likes .story__count-number"))),
            )
        )
    return items


# ---------------------------------------------------------------- 数据库内核月报


def _mysql_monthly_items(page_html: str) -> list[ListItem]:
    """目录页 h3 > a.main[href=/monthly/YYYY/MM],新的在前,一页列出全部期数。
    只有年月没有日,timestamp 留空。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for anchor in _soup(page_html).select("h3 > a[href]"):
        href = _attr(anchor, "href")
        match = re.search(r"/monthly/(\d{4})/(\d{2})/?$", href)
        if not match:
            continue
        url = urljoin("http://mysql.taobao.org/monthly/", href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            ListItem(
                id=f"{match.group(1)}/{match.group(2)}",
                title=_text(anchor),
                url=url,
                mobileUrl=url,
            )
        )
    return items


# ---------------------------------------------------------------- JavaScript Weekly


def _jsweekly_issue_items(page_html: str) -> list[ListItem]:
    """期刊页每篇是 span.mainlink > a(外链),所在 td 里 p.desc 是摘要、p.name 是作者/来源;
    p.name 里带 span.tag-sponsor 的是赞助内容(广告),跳过。条目日期即期刊日期,timestamp 留空。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for span in _soup(page_html).select("span.mainlink"):
        anchor = span.find("a")
        if not isinstance(anchor, Tag):
            continue
        url = _attr(anchor, "href")
        cell = span.find_parent("td")
        name = cell.select_one("p.name") if isinstance(cell, Tag) else None
        if name is not None and name.select_one(".tag-sponsor") is not None:
            continue
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        desc_tag = span.find_parent("p")
        desc = _text(desc_tag) if isinstance(desc_tag, Tag) else ""
        title = _text(anchor)
        if title and title in desc:  # 段落是"[emoji] 标题 — 摘要",去掉标题及其前面的部分
            desc = desc.split(title, 1)[1].lstrip(" —-–")
        items.append(
            ListItem(
                id=url,
                title=title,
                url=url,
                mobileUrl=url,
                author=(_text(name) or None) if name is not None else None,
                desc=desc[:500] or None,
            )
        )
    return items


# ---------------------------------------------------------------- 遥感学报


def _ygxb_current_path(page_html: str) -> str:
    """每个页面顶部菜单"期刊在线"下都有"当期目录"链接(/cn/issue/<年>/<期>),以它为准。"""
    match = re.search(r'href="(/cn/issue/\d{4}/\d{1,2})"[^>]*>当期目录<', page_html)
    return match.group(1) if match else ""


def _ygxb_issue_items(page_html: str, page_url: str) -> list[ListItem]:
    """期次页每篇:h3.resName > a(标题、/cn/article/doi/…)、em.authors-text(作者)、
    em.em-summary(摘要)、img.backIssueType_img(配图)。
    每篇的"更新时间"不一定是发布日期,timestamp 留空。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for heading in _soup(page_html).select("h3.resName"):
        anchor = heading.find("a")
        if not isinstance(anchor, Tag):
            continue
        href = _attr(anchor, "href")
        if "/article/" not in href:
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        block = heading.find_parent("li")
        authors = block.select_one("em.authors-text") if isinstance(block, Tag) else None
        summary = block.select_one("em.em-summary") if isinstance(block, Tag) else None
        image = _attr(block.select_one("img.backIssueType_img") if isinstance(block, Tag) else None, "src")
        desc = re.sub(r"^摘要[:：]\s*", "", _text(summary)) if summary else ""
        items.append(
            ListItem(
                id=href.rsplit("/doi/", 1)[-1] if "/doi/" in href else url,
                title=_text(anchor),
                url=url,
                mobileUrl=url,
                author=_text(authors) or None if authors else None,
                desc=desc[:500] or None,
                cover=urljoin(page_url, image) if image.startswith(("http", "/")) else None,
            )
        )
    return items


# ---------------------------------------------------------------- 阮一峰科技爱好者周刊


def _cfemail(hexstr: str) -> str:
    """Cloudflare 把形如 x@y 的文字替换成 data-cfemail(首字节是异或密钥),
    浏览器里由页面脚本还原;这里按同样规则还原。"""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def _ruanyifeng_items(page_html: str) -> list[ListItem]:
    """栏目页 h1"分类:周刊(共 N 篇文章)",下面按年分组(h3 年份 + ul.module-list),
    一页列出全部期数,新的在前。侧栏"分类"列表也是 module-list,但链接是 /blog/<分类>/,
    不匹配 /blog/YYYY/MM/*.html,自然排除。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for li in _soup(page_html).select("ul.module-list > li.module-list-item"):
        anchor = li.find("a", href=True)
        if not isinstance(anchor, Tag):
            continue
        url = urljoin("https://www.ruanyifeng.com/blog/weekly/", _attr(anchor, "href"))
        # 只要正文里的文章链接;第 261 期地址拼成了 weely-issue-261,所以不按 weekly-issue 匹配
        if not re.search(r"/blog/\d{4}/\d{2}/[^/]+\.html$", url) or url in seen:
            continue
        seen.add(url)
        match = re.search(r"issue-(\d+)\.html$", url)
        enc = li.select_one("[data-cfemail]")
        # "（N@YYYY.MM.DD）"被 Cloudflare 改写成 data-cfemail;没有混淆时直接取文字
        hint = _cfemail(_attr(enc, "data-cfemail")) if enc is not None else _text(li)
        date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", hint)
        stamp = (
            _zone_date_seconds(f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}", "%Y-%m-%d", _BEIJING)
            if date_match
            else None
        )
        items.append(
            ListItem(
                id=match.group(1) if match else url,  # 期号
                title=_text(anchor),
                url=url,
                mobileUrl=url,
                timestamp=get_time(stamp),  # 日期北京时间 0 点
            )
        )
    return items


# ---------------------------------------------------------------- 取数入口


async def _fetch_feed(board: str, no_cache: bool) -> tuple[Any, list[ListItem], str]:
    result = await get(
        url=_FEED_BOARDS[board],
        no_cache=no_cache,
        response_type="text",
    )
    items = parse_feed(str(result.data))
    if not items:
        raise RuntimeError(f"Tech blog feeds board '{board}' parsed no items from {_FEED_BOARDS[board]}")
    return result, items, ""


async def _fetch_devto_api(board: str, no_cache: bool) -> tuple[Any, list[ListItem], str]:
    days, _ = _DEVTO_API_BOARDS[board]
    result = await get(
        url=_DEVTO_API_URL,
        params={"top": str(days)},  # per_page 缺省就是 30,不传(min_request.log 实测)
        no_cache=no_cache,
        response_type="json",
    )
    items = [item for item in (_devto_api_item(row) for row in result.data or []) if item is not None]
    if not items:
        raise RuntimeError(f"Tech blog feeds board '{board}' parsed no items")
    return result, items, ""


async def _fetch_devto_stories(no_cache: bool) -> tuple[Any, list[ListItem], str]:
    result = await get(
        url=_DEVTO_STORIES_URL,
        params={"page": "1"},  # 页面首屏滚动加载的第 1 页(page_vs_output.md)
        no_cache=no_cache,
        response_type="json",
    )
    items = [item for item in (_devto_stories_item(row) for row in result.data or []) if item is not None]
    if not items:
        raise RuntimeError(f"Tech blog feeds board '{_DEVTO_STORIES_BOARD}' parsed no items")
    return result, items, ""


async def _fetch_html(board: str, no_cache: bool) -> tuple[Any, list[ListItem], str]:
    url = {
        "anond-popular": "https://anond.hatelabo.jp/archive",
        "producthunt-today": "https://www.producthunt.com/",
        "indiehackers-home": "https://www.indiehackers.com/",
        "mysql-monthly": "http://mysql.taobao.org/monthly/",
    }[board]
    result = await get(url=url, no_cache=no_cache, response_type="text")
    parse = {
        "anond-popular": _anond_items,
        "producthunt-today": _producthunt_items,
        "indiehackers-home": _indiehackers_items,
        "mysql-monthly": _mysql_monthly_items,
    }[board]
    items = parse(str(result.data))
    if not items:
        raise RuntimeError(f"Tech blog feeds board '{board}' parsed no items from {url}")
    return result, items, ""


async def _fetch_jsweekly(no_cache: bool) -> tuple[Any, list[ListItem], str]:
    """RSS 第一条的 link 是最新期号(/issues/latest 返回 400),再取期刊页。"""
    rss = await get(url="https://javascriptweekly.com/rss/", no_cache=no_cache, response_type="text")
    latest = parse_feed(str(rss.data))
    if not latest:
        raise RuntimeError("JavaScript Weekly RSS parsed no issues")
    issue = latest[0]
    match = re.search(r"/issues/(\d+)", issue.url)
    if not match:
        raise RuntimeError(f"JavaScript Weekly RSS first item is not an issue page: {issue.url}")
    result = await get(url=f"https://javascriptweekly.com/issues/{match.group(1)}", no_cache=no_cache, response_type="text")
    items = _jsweekly_issue_items(str(result.data))
    if not items:
        raise RuntimeError("JavaScript Weekly issue page parsed no items")
    # 条目的日期就是期刊日期,timestamp 留空;期号和日期写进 type
    day = (
        datetime.fromtimestamp(issue.timestamp / 1000, UTC).strftime("%Y-%m-%d")
        if issue.timestamp
        else ""
    )
    suffix = f"#{match.group(1)}" + (f"（{day}）" if day else "")
    return result, items, suffix


async def _fetch_ygxb(no_cache: bool) -> tuple[Any, list[ListItem], str]:
    """先取按北京时间当月猜的期次页,以页面菜单"当期目录"为准(还没出的期次页也是 200,0 篇)。"""
    now = datetime.now(_BEIJING)
    guess = f"https://www.ygxb.ac.cn/cn/issue/{now.year}/{now.month}"
    result = await get(url=guess, no_cache=no_cache, response_type="text")
    current = _ygxb_current_path(str(result.data))
    if not current:
        raise RuntimeError("YGXB page menu has no '当期目录' link (page changed)")
    if urlsplit(guess).path != current:
        result = await get(url=urljoin(guess, current), no_cache=no_cache, response_type="text")
    items = _ygxb_issue_items(str(result.data), guess)  # 链接都是根相对,用请求地址补全即可
    if not items:
        raise RuntimeError(f"YGXB current issue page {current} parsed no items")
    match = re.search(r"/issue/(\d{4})/(\d{1,2})", current)
    suffix = f"{match.group(1)} 年第 {match.group(2)} 期" if match else ""
    return result, items, suffix


async def _fetch_ruanyifeng(no_cache: bool) -> tuple[Any, list[ListItem], str]:
    # whatshot 既有 ruanyifeng-weekly 路由抓全博客 atom.xml;本子榜照 board_api 证据改用周刊栏目页
    result = await get(
        url="https://www.ruanyifeng.com/blog/weekly/index.html",
        no_cache=no_cache,
        response_type="text",
        headers={"User-Agent": _BROWSER_UA},
    )
    items = _ruanyifeng_items(str(result.data))
    if not items:
        raise RuntimeError("Ruanyifeng weekly category page parsed no issues")
    return result, items, ""


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in type_map:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")

    if selected in _DEVTO_API_BOARDS:
        result, data, suffix = await _fetch_devto_api(selected, no_cache)
    elif selected == _DEVTO_STORIES_BOARD:
        result, data, suffix = await _fetch_devto_stories(no_cache)
    elif selected in _FEED_BOARDS:
        result, data, suffix = await _fetch_feed(selected, no_cache)
    elif selected == "jsweekly-latest":
        result, data, suffix = await _fetch_jsweekly(no_cache)
    elif selected == "ygxb-latest":
        result, data, suffix = await _fetch_ygxb(no_cache)
    elif selected == "ruanyifeng-weekly":
        result, data, suffix = await _fetch_ruanyifeng(no_cache)
    else:
        result, data, suffix = await _fetch_html(selected, no_cache)

    if not data:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"Tech blog feeds board '{selected}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[selected] + (f" · {suffix}" if suffix else ""),
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
