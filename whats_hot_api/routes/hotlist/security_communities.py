"""安全与破解社区：吾爱破解、先知社区、FreeBuf、安全内参（多站点，type=站点-栏目）。

迁移自 board_api security_communities 单元（9 个已完成榜），每个子榜 1 个请求：
- 吾爱破解（www.52pojie.cn，Discuz!，GBK）4 个榜，都是服务端渲染的 HTML 页面：
  首页 toplist 插件的「人气热门」列（``table.toplist_7ree``，表头定位列）、排行榜
  「帖子热度排行 · 今日」（``misc.php?mod=ranklist&type=thread&view=heats&orderby=today``）、
  原创发布区（fid=2）与精品软件区（fid=16）版块页的「最新」视图
  （``filter=author&orderby=dateline``，按发帖时间）。版块页照原站页面顺序输出：
  先置顶帖（``tbody[id^=stickthread_]``，desc 标"置顶"），再普通主题（normalthread_）。
  帖子链接统一成 ``thread-<tid>-1-1.html``（页面里还有 ``forum.php?mod=viewthread&tid=…`` 形式）。
  站点前面有 WAF（wzws），会间歇地把请求 302 到滑块验证页：按 board_api 决定只用
  项目缺省 Chrome UA，遇到滑块页（正文有 ``wzws-waf-cgi`` / ``waf_slider``）直接报错，
  不重试、不换 UA、不执行验证脚本。tophub「最新帖子」与导读「最新发表」是同一份列表，
  whatshot /52pojie/newthread 已支持，本路由不再提供
- 先知社区（xz.aliyun.com）2 个榜：
  「最新」取官方 Atom ``/feed``（标题"先知安全技术社区"，100 条，按文章 id 倒序，照 feed 原顺序）。
  /news 页没有"最新"页签，全部分类的 ajax ``type=category&category=0`` 只出现在服务端写死
  ``if (0 == 0)`` 的 else 分支里，页面发不出，所以不用（board_api 2026-09-30 推翻性验证）。
  「精选文章」是 /news 首屏缺省页签，页面发出的 ajax ``/news?isAjax=true&type=recommend``
  必须带 ``X-Requested-With: XMLHttpRequest``，否则返回整页 HTML；返回 ``{data: HTML 片段}``。
  两处的时间都是不带时区的 UTC（feed 频道 <updated> 带 +00:00，条目时间与它同一时刻），按 UTC 换算
- FreeBuf（www.freebuf.com）2 个榜：首页是 Nuxt 前端渲染（whatshot 既有 freebuf 路由解析
  ``.article-item`` 已取到 0 条），本路由改走页面自己的列表接口
  ``/fapi/frontend/home/article``，参数取自页面 JS 的缺省值（page=1、limit=20、category=精选）；
  type=1 是「最新」，type=2 + day=7 是「热榜 · 7 天内」（按阅读数）。对程序 UA 会返回
  阿里云 WAF 的 JS 挑战页，必须带浏览器 UA（board_api 实测项目缺省 UA 直接通过，间歇拦截时
  拿到非 JSON 就报错，不执行挑战脚本）；type=1 时 day 不起作用，照页面带上
- 安全内参（www.secrss.com）1 个榜：首页「最新资讯」。首屏服务端渲染 20 条，「加载更多」调用
  ``/api/articles``；不带 ``lastPublishedAt`` 时返回的就是首屏那 20 条（逐条同序），且带精确到秒的
  发布时间，所以取接口。业务壳是 ``{"code": "10000", data: [...]}``，其他 code 按业务错误报错

看雪「最新精华」要登录（new-digest.htm 访客只有"请先登录"，/rss.htm 404），不迁（board_api README）。
请求头照 board_api 证据：全部站点用项目缺省 Chrome UA + Accept-Language；先知精选 ajax 另带
X-Requested-With；吾爱破解限速 3 秒/次由部署侧保障（路由层无状态，不做进程内限速）。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "security-communities"

_TYPE_MAP: dict[str, str] = {
    "52pojie-hot": "吾爱破解 · 人气热门",
    "52pojie-today-heats": "吾爱破解 · 今日热帖（帖子热度排行 · 今日）",
    "52pojie-original": "吾爱破解 · 原创发布区（最新发表）",
    "52pojie-software": "吾爱破解 · 精品软件区（最新发表）",
    "xz-latest": "先知社区 · 最新文章",
    "xz-recommend": "先知社区 · 精选文章",
    "freebuf-latest": "FreeBuf · 最新",
    "freebuf-weekly-hot": "FreeBuf · 热榜（7 天内）",
    "secrss-latest": "安全内参 · 最新资讯",
}

_DEFAULT_TYPE = "52pojie-hot"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "安全与破解社区",
    "description": "吾爱破解（人气热门、今日热帖、原创发布区、精品软件区）、先知社区（最新、精选文章）、FreeBuf（最新、7 天热榜）、安全内参最新资讯。",
    "link": "https://www.52pojie.cn/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_JSON_ACCEPT = "application/json, text/plain, */*"
# board_api 证据的全部请求都带这组客户端头（common.http.DEFAULT_HEADERS）；
# 吾爱破解 WAF 间歇出滑块时任何 UA 都拦（不换 UA），FreeBuf 对程序 UA 必拦（浏览器 UA 直接通过）
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# ---------------------------------------------------------------- 吾爱破解

_POJIE = "https://www.52pojie.cn/"
# 子榜 -> (页面地址, 解析方式)
_POJIE_PAGES: dict[str, tuple[str, str]] = {
    "52pojie-hot": (_POJIE, "toplist"),
    "52pojie-today-heats": (_POJIE + "misc.php?mod=ranklist&type=thread&view=heats&orderby=today", "ranklist"),
    "52pojie-original": (_POJIE + "forum.php?mod=forumdisplay&fid=2&filter=author&orderby=dateline", "threadlist"),
    "52pojie-software": (_POJIE + "forum.php?mod=forumdisplay&fid=16&filter=author&orderby=dateline", "threadlist"),
}
_POJIE_TOPLIST_COLUMN = "人气热门"

# ---------------------------------------------------------------- 先知社区

_XZ_FEED = "https://xz.aliyun.com/feed"
_XZ_NEWS = "https://xz.aliyun.com/news"
# /news 首屏的 getNewsList(params) 与点「精选文章」页签时发出的参数；
# 必须带 X-Requested-With（页面的 axios 全局设了这个头），否则 Laravel 返回整页 HTML
_XZ_RECOMMEND_PARAMS = {"isAjax": "true", "type": "recommend"}
_XZ_RECOMMEND_HEADERS = {
    **_BASE_HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": _JSON_ACCEPT,
    "Referer": "https://xz.aliyun.com/news",
}

# ---------------------------------------------------------------- FreeBuf

_FREEBUF = "https://www.freebuf.com/"
_FREEBUF_API = "https://www.freebuf.com/fapi/frontend/home/article"
# 页面 JS 的缺省参数 parmas:{page:1,limit:20,type:"1",day:7,category:"精选"}；点「热榜」时 type=2（day=7，7 天内）
_FREEBUF_PARAMS: dict[str, dict[str, Any]] = {
    "freebuf-latest": {"page": 1, "limit": 20, "type": 1, "day": 7, "category": "精选"},
    "freebuf-weekly-hot": {"page": 1, "limit": 20, "type": 2, "day": 7, "category": "精选"},
}

# ---------------------------------------------------------------- 安全内参

_SECRSS_API = "https://www.secrss.com/api/articles"
# 与首页 common.js loadArticles 相同的请求头；实测都不必需，照页面带上
_SECRSS_HEADERS = {
    **_BASE_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.secrss.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    site = board.split("-", 1)[0]
    fetchers = {
        "52pojie": _get_52pojie,
        "xz": _get_xz,
        "freebuf": _get_freebuf,
        "secrss": _get_secrss,
    }
    list_data = await fetchers[site](board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


def _finish(result: RequestResult, items: list[ListItem], message: str | None = None) -> dict:
    if not items and message is None:
        raise RuntimeError(f"{ROUTE_NAME} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": message,
    }


def _gbk_text(result: RequestResult) -> str:
    """吾爱破解 / 其他 GBK 页面按 GB18030（超集）解码，避免 gb2312 解不了的字变乱码。"""
    text = result.data.decode("gb18030", "replace") if isinstance(result.data, bytes) else str(result.data)
    if "wzws-waf-cgi" in text or "waf_slider" in text or "请完成安全验证" in text:
        # WAF 间歇把请求 302 到滑块验证页（follow_redirects 后拿到的是 200 的滑块页）。
        # 按 board_api 决定：不重试、不换 UA、不执行验证脚本，这次取不到就稍后再运行
        raise RuntimeError(
            "52pojie returned the wzws WAF slider verification page (intermittent), "
            "not retrying or switching UA per board_api decision"
        )
    return text


def _discuz_ts(value: str) -> int | None:
    """Discuz 时间串："2026-9-28 07:50"、"2026-09-28 07:50:30" 或纯日期；只认绝对时间，
    不把"N 小时前"这类相对显示换算成本机时间（与 board_api 口径一致，相对显示时留空）。"""
    if not re.search(r"\d{4}-\d{1,2}-\d{1,2}", value or ""):
        return None
    return get_time(value.strip())


def _discuz_em_ts(em: Tag | None) -> int | None:
    """td.by em 里的发帖时间：一般直接是"2026-9-28 07:50"；较新的帖子 Discuz 显示"N 小时前"，
    完整时间在 span 的 title 里。"""
    if em is None:
        return None
    span = em.select_one("span[title]")
    if span is not None:
        ts = _discuz_ts(str(span.get("title") or ""))
        if ts is not None:
            return ts
    return _discuz_ts(_text(em))


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _int(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _tid(href: str) -> str | None:
    match = re.search(r"thread-(\d+)-|[?&]tid=(\d+)", href or "")
    if not match:
        return None
    return match.group(1) or match.group(2)


def _pojie_url(tid: str) -> str:
    # 页面上的链接有 thread-<tid>-1-1.html 与 forum.php?mod=viewthread&tid=<tid> 两种，统一成前者
    return f"{_POJIE}thread-{tid}-1-1.html"


async def _get_52pojie(board: str, no_cache: bool) -> dict:
    url, kind = _POJIE_PAGES[board]
    result = await get(
        url=url,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="arraybuffer",  # 字节流自己按 GBK 解码，不依赖响应头 charset
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    html = _gbk_text(result)
    soup = BeautifulSoup(html, "lxml")
    if kind == "toplist":
        items = _pojie_toplist(soup)
    elif kind == "ranklist":
        items = _pojie_ranklist(soup)
    else:
        items = _pojie_threadlist(soup)
    return _finish(result, items)


def _pojie_toplist(soup: BeautifulSoup) -> list[ListItem]:
    """首页 toplist_7ree 表：tr.toptitle_7ree 是表头一行，tr.fl_row 每列一个列表。"""
    table = soup.select_one("table.toplist_7ree")
    if table is None:
        raise RuntimeError("52pojie home page has no toplist_7ree table (page changed)")
    heads = [_text(td) for td in table.select("tr.toptitle_7ree > td")]
    cols = table.select("tr.fl_row > td")
    index = next((i for i, head in enumerate(heads) if head.startswith(_POJIE_TOPLIST_COLUMN)), None)
    if index is None or index >= len(cols):
        raise RuntimeError(
            f"52pojie home toplist has no '{_POJIE_TOPLIST_COLUMN}' column (headers: {heads})"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for line in cols[index].select("div.threadline_7ree"):
        a = line.select_one("a[href]")
        if a is None:
            continue
        tid = _tid(str(a.get("href") or ""))
        title = _text(a)
        if not tid or not title or tid in seen:
            continue
        seen.add(tid)
        tips = str(a.get("tips") or "")
        # 列表里的标题过长时被截成"….."，完整标题在悬停提示 tips 的 <strong> 里
        full = re.search(r"<strong[^>]*>(.*?)</strong>", tips, re.DOTALL)
        if full is not None and _text(BeautifulSoup(full.group(1), "lxml")):
            title = _text(BeautifulSoup(full.group(1), "lxml"))
        forum = re.search(r"版块：\s*([^<\n]+)", tips)
        author = re.search(r"作者：\s*([^<\n]+)", tips)
        when = re.search(r"时间：\s*([\d\- :]+)", tips)
        items.append(
            ListItem(
                id=tid,
                title=title,
                url=_pojie_url(tid),
                mobileUrl=_pojie_url(tid),
                author=author.group(1).strip() if author else None,
                desc=forum.group(1).strip() if forum else None,
                timestamp=_discuz_ts(when.group(1)) if when else None,
            )
        )
    return items


def _pojie_ranklist(soup: BeautifulSoup) -> list[ListItem]:
    """排行榜 div.tl 表：主题 / 版块 / 作者（带发帖时间）/ 热度。"""
    table = soup.select_one("div.tl table")
    if table is None:
        raise RuntimeError("52pojie ranklist page has no div.tl table (page changed)")
    items: list[ListItem] = []
    seen: set[str] = set()
    for tr in table.select("tr"):
        if "th" in (tr.get("class") or []):
            continue
        a = tr.select_one("th a[href]")
        if a is None:
            continue
        tid = _tid(str(a.get("href") or ""))
        title = _text(a)
        if not tid or not title or tid in seen:
            continue
        seen.add(tid)
        tds = tr.find_all("td", recursive=False)
        by = tr.select_one("td.by")
        items.append(
            ListItem(
                id=tid,
                title=title,
                url=_pojie_url(tid),
                mobileUrl=_pojie_url(tid),
                hot=_int(_text(tds[-1])) if tds else None,
                author=_text(by.select_one("cite")) if by else None,
                desc=_text(tr.select_one("td.frm")) or None,
                timestamp=_discuz_em_ts(by.select_one("em") if by else None),
            )
        )
    return items


def _pojie_threadlist(soup: BeautifulSoup) -> list[ListItem]:
    """版块页主题列表：先置顶帖（stickthread_），再普通主题（normalthread_），与页面顺序一致。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for tbody in soup.select("tbody[id^=stickthread_], tbody[id^=normalthread_]"):
        raw_id = str(tbody.get("id") or "")
        tid = raw_id.split("_", 1)[-1]
        a = tbody.select_one("a.xst")
        if not tid.isdigit() or a is None or tid in seen:
            continue
        title = _text(a)
        if not title:
            continue
        seen.add(tid)
        by = tbody.select_one("td.by")  # 第一个 td.by 是作者 + 发帖时间，最后一个是最后回复
        num = tbody.select_one("td.num em")
        items.append(
            ListItem(
                id=tid,
                title=title,
                url=_pojie_url(tid),
                mobileUrl=_pojie_url(tid),
                hot=_int(_text(num)) if num else None,
                author=(_text(by.select_one("cite")) or None) if by else None,
                desc="置顶" if raw_id.startswith("stick") else None,
                timestamp=_discuz_em_ts(by.select_one("em") if by else None),
            )
        )
    return items


# ---------------------------------------------------------------- 先知社区


def _xz_utc_ms(value: str) -> int | None:
    """先知的时间串（feed 的 published、列表片段里的发布时间）是 UTC、不带时区：
    feed 频道 <updated> 写 2026-09-30T14:08:56+00:00，条目 <updated> 同一时刻写 2026-09-30 14:08:48。"""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(value, fmt).replace(tzinfo=UTC).timestamp() * 1000)
        except ValueError:
            continue
    return None


async def _get_xz(board: str, no_cache: bool) -> dict:
    if board == "xz-latest":
        result = await get(
            url=_XZ_FEED,
            headers={**_BASE_HEADERS, "Accept": "application/atom+xml,application/xml,text/xml,*/*"},
            no_cache=no_cache,
            response_type="text",
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        items = _xz_feed_items(str(result.data))
    else:
        result = await get(
            url=_XZ_NEWS,
            params=_XZ_RECOMMEND_PARAMS,
            headers=_XZ_RECOMMEND_HEADERS,
            no_cache=no_cache,
            response_type="text",
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        items = _xz_recommend_items(result.data)
    return _finish(result, items)


def _xz_feed_items(xml_text: str) -> list[ListItem]:
    """官方 Atom /feed：照 feed 原顺序（文章 id 倒序）输出；时间按 UTC 换算。

    拿不到 Atom（阿里云 WAF 挑战页是 HTML）时直接报错，不执行挑战脚本。
    """
    soup = BeautifulSoup(xml_text, "xml")
    if soup.find("feed") is None:
        raise RuntimeError(
            f"xianzhi /feed did not return an Atom document (aliyun WAF challenge: {'aliyun_waf' in xml_text[:4000]})"
        )
    items: list[ListItem] = []
    for entry in soup.find_all("entry"):
        link = entry.find("link")
        title = _tag_text(entry, "title")
        href = str(link.get("href") or "").strip() if link is not None else ""
        match = re.search(r"/news/(\d+)", href)
        if not match or not title or not href:
            continue
        items.append(
            ListItem(
                id=match.group(1),
                title=title,
                url=href,
                mobileUrl=href,
                desc=_tag_text(entry, "summary") or None,
                # feed 没有 hot / author；published 是不带时区的 UTC
                timestamp=_xz_utc_ms(_tag_text(entry, "published")),
            )
        )
    return items


def _tag_text(node: Tag, name: str) -> str:
    child = node.find(name)
    return child.get_text(strip=True) if child is not None else ""


def _xz_recommend_items(payload: Any) -> list[ListItem]:
    """精选文章 ajax 片段：每条 div.news_item（标题、摘要、作者、浏览数、发布时间、配图）。"""
    if not isinstance(payload, str):
        payload = str(payload)
    if "aliyun_waf" in payload[:4000]:
        raise RuntimeError("xianzhi /news ajax returned an aliyun WAF challenge page, not executing the challenge script")
    try:
        envelope: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        # 缺 X-Requested-With 时 Laravel 返回整页 HTML 而不是 JSON
        raise RuntimeError(f"xianzhi /news ajax did not return JSON (missing X-Requested-With?): {str(payload)[:120]!r}") from exc
    fragment = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(fragment, str) or not fragment:
        raise RuntimeError("xianzhi /news ajax response has no data fragment (envelope changed)")
    soup = BeautifulSoup(fragment, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for div in soup.select("div.news_item"):
        a = div.select_one("a.news_title")
        if a is None:
            continue
        url = str(a.get("href") or "").strip()
        match = re.search(r"/news/(\d+)", url)
        title = _text(a)
        if not match or not title or not url or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        img = div.select_one(".news_img img")
        cover = str(img.get("src") or "").strip() if img else ""
        user = div.select_one(".news_bm a.user-info span")
        meta = _text(div.select_one(".news_bm"))
        views = re.search(r"(\d+)\s*浏览", meta)
        when = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", meta)
        items.append(
            ListItem(
                id=match.group(1),
                title=title,
                url=url,
                mobileUrl=url,
                cover=cover if cover.startswith("http") else None,
                author=_text(user) or None,
                desc=_text(div.select_one(".news_word > p")) or None,
                hot=int(views.group(1)) if views else None,
                timestamp=_xz_utc_ms(when.group(1)) if when else None,
            )
        )
    return items


# ---------------------------------------------------------------- FreeBuf


async def _get_freebuf(board: str, no_cache: bool) -> dict:
    result = await get(
        url=_FREEBUF_API,
        params=_FREEBUF_PARAMS[board],
        headers={**_BASE_HEADERS, "Accept": _JSON_ACCEPT, "Referer": _FREEBUF},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    text = result.data if isinstance(result.data, str) else str(result.data)
    if "aliyun_waf" in text[:4000]:
        # 程序 UA 会拿到阿里云 WAF 的 JS 挑战页；浏览器 UA 间歇也会被拦。不执行挑战脚本
        raise RuntimeError("freebuf returned an aliyun WAF JS challenge page, not executing the challenge script")
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"freebuf did not return JSON (content changed): {text[:120]!r}") from exc
    if payload.get("code") != 200:
        raise RuntimeError(f"freebuf API returned code={payload.get('code')} msg={payload.get('msg')}")
    rows = (payload.get("data") or {}).get("list")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
        "freebuf API response has no data.list (feed changed)"
    )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("ID")
        title = str(row.get("post_title") or "").strip()
        link = str(row.get("url") or "").strip()
        if not item_id or not title or not link:
            continue
        url = urljoin(_FREEBUF, link)
        items.append(
            ListItem(
                id=str(item_id),
                title=title,
                url=url,
                mobileUrl=url,
                cover=row.get("post_image") or row.get("column_post_picture") or None,
                author=row.get("nickname") or row.get("username") or None,
                desc=row.get("content") or None,
                hot=row.get("read_count"),
                timestamp=get_time(str(row.get("post_date") or "")),
            )
        )
    return _finish(result, items)


# ---------------------------------------------------------------- 安全内参


async def _get_secrss(board: str, no_cache: bool) -> dict:
    # 首屏不带 lastPublishedAt 游标，返回的就是首页「最新资讯」那 20 条（逐条同序）
    result = await get(
        url=_SECRSS_API,
        params={"referer": "web"},
        headers=_SECRSS_HEADERS,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    text = result.data if isinstance(result.data, str) else str(result.data)
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"secrss did not return JSON (content changed): {text[:120]!r}") from exc
    if str(payload.get("code")) != "10000":
        raise RuntimeError(f"secrss API returned code={payload.get('code')} msg={payload.get('msg')}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
        "secrss API response has no data list (feed changed)"
    )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("id")
        title = str(row.get("title") or "").strip()
        if not item_id or not title:
            continue
        url = f"https://www.secrss.com/articles/{item_id}"
        items.append(
            ListItem(
                id=str(item_id),
                title=title,
                url=url,
                mobileUrl=url,
                cover=row.get("thumb_image_url") or row.get("image_url") or None,
                author=row.get("author") or row.get("source_author") or None,
                desc=row.get("summary") or None,
                hot=row.get("hit_num"),
                timestamp=get_time(str(row.get("published_at") or "")),
            )
        )
    return _finish(result, items)
