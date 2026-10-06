"""其他时政媒体(多站点,type=站点-栏目)。

迁移自 board_api ``tmp/board_api/politics_media`` 单元(11 个站点的 16 个已完成榜),
逐榜数据源与认榜依据见该目录 README / analysis_report,证据目录 ``evidence/``。
全部公开、无签名、无 cookie、无需登录。board_api 的全部请求都带浏览器 UA
(央广网不带 UA 403,观察者网 curl 缺省 UA 返回 JS 挑战页),这里照常带。

- 观察者网 4 个:首页用 ``html.parser`` 解析(页面 ``li`` 嵌套不规范,lxml 会把中栏
  截成 1 条);时评页、国际栏目列表用 lxml。timestamp 取文章地址里的日期,时评、
  国际列表取页面时间
- 环球网国际:频道首页主信息流"最新消息",先取 ``/api/channel_pc`` 的栏目节点,
  再请求 ``/api/list?node=…&offset=0&limit=24``(limit=24 是页面组件缺省值,
  返回末尾多一个空对象);X-Requested-With 实测非必需,照页面带上
- 参考消息:``/json/channel/yaowen/list.json``,首页"要闻"模块,编辑顺序
- 凤凰热榜:``ishare.ifeng.com/hotNewsRank`` 页内嵌 ``var allData = {…}``;
  链接用页面自己用的 ``link.weburl``(ishare 分享页)
- 中国新闻周刊 2 个:首页 GBK,十大热文 ``div.sin_top10_cont``、首页推荐
  ``div.grid-item``(置顶 4 条 + 瀑布流首屏 19 条,中间被注释掉的 ten_text 不算);
  timestamp 取地址里的日期
- China Daily 2 个:官方 RSS 均已 404(tophub 停更),按栏目页取——China News 取
  China 频道 Latest 列表;China Daily News 取报纸电子版最近一期(入口 301 指向
  2021 年,从北京时间今天往前逐日找第一个有文章的日期,周日无报,最多回看 7 天)
- 央广网滚动:GBK;链接里的 ``?sign=…`` 是 TRS 预览参数,输出时去掉
- 中国科技网滚动、南风窗首页推荐、求是网头条(首页 ``div.headtitle``)、
  《求是》最新期刊(首页"往期"数据文件第 1 行 → 目录页 ``#detailContent``)
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import CHINA_TZ, get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "politics-media"

# 声明序第一个是默认榜(board_api 的 DEFAULT_TYPE=guancha-yaowen)
_TYPE_MAP: dict[str, str] = {
    "guancha-yaowen": "观察者网 · 要闻",
    "guancha-top": "观察者网 · 首页新闻",
    "guancha-shiping": "观察者网 · 时评",
    "guancha-intl": "观察者网 · 国际新闻",
    "huanqiu-world": "环球网 · 国际新闻",
    "cankaoxiaoxi-yaowen": "参考消息 · 滚动新闻",
    "ifeng-hot": "凤凰网 · 凤凰热榜",
    "inewsweek-top10": "中国新闻周刊 · 十大热文",
    "inewsweek-rec": "中国新闻周刊 · 首页推荐",
    "chinadaily-epaper": "China Daily · China Daily News",
    "chinadaily-china": "China Daily · China News",
    "cnr-roll": "央广网 · 滚动快讯",
    "stdaily-roll": "中国科技网 · 滚动新闻",
    "nfcmag-home": "南风窗 · 首页推荐",
    "qstheory-headline": "求是网 · 头条",
    "qstheory-issue": "《求是》 · 最新期刊",
}

_DEFAULT_TYPE = next(iter(_TYPE_MAP))

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "时政媒体",
    "description": (
        "观察者网、环球网、参考消息、凤凰网、中国新闻周刊、China Daily、"
        "央广网、中国科技网、南风窗、求是网的栏目列表"
    ),
    "link": "https://www.guancha.cn/",
    "params": {"type": {"name": "站点栏目", "type": _TYPE_MAP}},
}

# board_api common.http 的缺省请求头(央广网不带 UA 403,观察者网 curl 缺省 UA 出挑战页)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

_GUANCHA = "https://www.guancha.cn/"
_GUANCHA_SP = "https://www.guancha.cn/mainnews-sp/"
_GUANCHA_INTL = "https://www.guancha.cn/column/GuoJi·ZhanLue/1"
_HUANQIU = "https://world.huanqiu.com/"
_CKXX = "https://www.cankaoxiaoxi.com/"
_IFENG = "https://ishare.ifeng.com/hotNewsRank"
_INEWSWEEK = "https://www.inewsweek.cn/"
_EPAPER = "http://epaper.chinadaily.com.cn/china/"
_CHINADAILY_CHINA = "https://www.chinadaily.com.cn/china/59b8d010a3108c54ed7dfc23"
_CNR = "https://news.cnr.cn/kuaixun/"
_STDAILY = "https://www.stdaily.com/web/gdxw/node_324.html"
_NFCMAG = "https://www.nfcmag.cn/"
_QSTHEORY = "https://www.qstheory.cn/"
_QSTHEORY_DS = "/ds_32929c18a87a4be0b577ff0591492df5.json"

# "2026-09-27 22:56:14"、"2026-09-27  22:23"、"2026-09-27" → 北京时间
_DATE_TIME = re.compile(
    r"(\d{4})\D(\d{1,2})\D(\d{1,2})(?:\D{1,3}(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
# 文章地址里的日期:观察者网 /2026_09_27_902413.shtml、中国新闻周刊 /2026-09-24/32324.shtml、
# 求是 /20260915/<32 位>/c.html、China Daily /a/202609/27/
_URL_DATE = re.compile(r"/(\d{4})[_-]?(\d{2})[_-]?(\d{2})(?:_\d+\.shtml|/)")
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(万|亿)?")
_COUNT_UNIT = {"万": 10_000, "亿": 100_000_000}

# 每个站点 fetcher 的返回:(from_cache, update_time, items)
_Fetch = tuple[bool, str, list[ListItem]]


def _clean(node: Tag | None) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""


def _date_ms(text: str | None) -> int | None:
    """页面时间文本 → 毫秒;只有日期时取当天 0 点(北京时间)。"""
    match = _DATE_TIME.search(text or "")
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=CHINA_TZ,
        )
    except ValueError:
        return None
    return get_time(int(dt.timestamp()))


def _url_date_ms(url: str) -> int | None:
    match = _URL_DATE.search(url)
    return _date_ms("-".join(match.groups())) if match else None


def _hot(text: str) -> int | None:
    """"阅读 60236"、"297万热度"、"1.2亿" → 整数。"""
    match = _COUNT.search(text or "")
    if not match:
        return None
    return round(float(match.group(1)) * _COUNT_UNIT.get(match.group(2) or "", 1))


def _cover(node: Tag | None, base: str) -> str | None:
    """条目里第一张图(data-original / original / src),相对地址按页面补全。"""
    if node is None:
        return None
    img = node.find("img")
    if not isinstance(img, Tag):
        return None
    src = img.get("data-original") or img.get("original") or img.get("src")
    return urljoin(base, str(src)) if src else None


class _Collector:
    """按页面顺序收条目,同一链接只留第一次(页面上重复出现的轮播、同一篇的多个入口)。"""

    def __init__(self) -> None:
        self.items: list[ListItem] = []
        self._seen: set[str] = set()

    def add(
        self, *, item_id: str | None = None, title: str, url: str, **fields: Any
    ) -> None:
        title = " ".join((title or "").split())
        if not title or not url or url in self._seen:
            return
        self._seen.add(url)
        self.items.append(
            ListItem(id=item_id or url, title=title, url=url, mobileUrl=url, **fields)
        )


async def _fetch(
    url: str,
    no_cache: bool,
    cache_key: str | None = None,
    *,
    response_type: str = "text",
    headers: dict[str, str] | None = None,
) -> RequestResult:
    return await get(
        url=url,
        headers={**_BASE_HEADERS, **(headers or {})},
        no_cache=no_cache,
        cache_key=cache_key,
        response_type=response_type,
    )


async def _fetch_html(
    url: str, no_cache: bool, cache_key: str | None = None
) -> RequestResult:
    """取 HTML 文本。"""
    return await _fetch(url, no_cache, cache_key, response_type="text")


async def _fetch_gbk_html(
    url: str, no_cache: bool, cache_key: str | None = None
) -> RequestResult:
    """GBK / GB2312 页面按 GB18030(超集)解码,避免 gb2312 解不了的字变成乱码。"""
    result = await _fetch(url, no_cache, cache_key, response_type="arraybuffer")
    text = (
        result.data.decode("gb18030", "replace")
        if isinstance(result.data, bytes)
        else str(result.data)
    )
    return RequestResult(result.from_cache, result.update_time, text)


def _html(result: RequestResult) -> str:
    return result.data if isinstance(result.data, str) else ""


def _soup(html: str, parser: str = "lxml") -> BeautifulSoup:
    return BeautifulSoup(html, parser)


def _meta(result: RequestResult) -> tuple[bool, str]:
    return result.from_cache, result.update_time


# ---------------------------------------------------------------- 观察者网


def _parse_guancha_top(html: str, page: str) -> list[ListItem]:
    """首页顶端:头条轮播 div.content-topnews-box-neo-box(同一组链接重复 9 份,
    只取第一次)+ 头条 div.content-headline。"""
    soup = _soup(html, "html.parser")
    out = _Collector()
    for a in soup.select("div.content-topnews-box-neo-box a[href]"):
        url = urljoin(page, str(a["href"]))
        out.add(title=_clean(a), url=url, timestamp=_url_date_ms(url))
    head = soup.select_one("div.content-headline")
    if head is not None:
        a = head.select_one("h3 a[href]")
        if a is not None:
            url = urljoin(page, str(a["href"]))
            creator = head.select_one(".module-interact-creator")
            reads = head.find("a", attrs={"data-sensor": "阅读数"})
            out.add(
                title=_clean(a),
                url=url,
                timestamp=_url_date_ms(url),
                cover=_cover(head, page),
                author=_clean(creator) or None,
                hot=_hot(_clean(reads)) if reads else None,
            )
    return out.items


def _parse_guancha_yaowen(html: str, page: str) -> list[ListItem]:
    """首页中栏 li.middle("更多"链到 /mainnews-yw/):每条 h4.module-title,
    配图、作者、阅读数在同一个 li 里。html.parser 解析才能保留整栏。"""
    mid = _soup(html, "html.parser").select_one("li.middle")
    if mid is None:
        raise RuntimeError(
            "guancha home has no li.middle (page changed)"
        )
    out = _Collector()
    for h4 in mid.select("h4.module-title"):
        a = h4.find("a", href=True)
        if not isinstance(a, Tag):
            continue
        url = urljoin(page, str(a["href"]))
        box = h4.parent if isinstance(h4.parent, Tag) else None
        creator = box.select_one(".module-interact-creator") if box else None
        reads = box.find("a", attrs={"data-sensor": "阅读数"}) if box else None
        pic = box.select_one(".fastRead-img") if box else None
        out.add(
            title=_clean(a),
            url=url,
            timestamp=_url_date_ms(url),
            cover=_cover(pic, page),
            author=_clean(creator) or None,
            hot=_hot(_clean(reads)) if isinstance(reads, Tag) else None,
        )
    return out.items


def _parse_guancha_shiping(html: str, page: str) -> list[ListItem]:
    """时评页 /mainnews-sp/:头条 div.tsp-list1 + "热点热评" ul.tsp-list2-list
    (编辑顺序,含置顶的旧文)。"""
    soup = _soup(html)
    out = _Collector()
    first = soup.select_one("div.tsp-list1")
    if first is not None:
        a = first.select_one("a.tsp-list1-title[href]")
        if a is not None:
            url = urljoin(page, str(a["href"]))
            out.add(
                title=_clean(a),
                url=url,
                timestamp=_url_date_ms(url),
                cover=_cover(first, page),
                author=_clean(first.select_one(".tsp-list1-name")) or None,
            )
    for li in soup.select("ul.tsp-list2-list > li"):
        a = li.select_one("a.tsp-list2-title[href]")
        if a is None:
            continue
        url = urljoin(page, str(a["href"]))
        review = li.select_one(".tsp-list2-review")
        spans = review.find_all("span") if review else []
        out.add(
            title=_clean(a),
            url=url,
            author=_clean(li.select_one(".tsp-list2-name")) or None,
            desc=_clean(li.select_one(".tsp-list2-content")) or None,
            timestamp=_date_ms(_clean(spans[-1])) if spans else _url_date_ms(url),
        )
    return out.items


def _parse_guancha_column(html: str, page: str) -> list[ListItem]:
    """栏目列表页 /column/<栏目>/<页码>:ul.column-list > li,h4 标题、
    p.module-artile 导语、span 发布时间。"""
    soup = _soup(html)
    out = _Collector()
    for li in soup.select("ul.column-list > li"):
        a = li.select_one("h4.module-title a[href]")
        if a is None:
            continue
        url = urljoin(page, str(a["href"]))
        desc = li.select_one("p.module-artile")
        if desc is not None:
            for extra in desc.find_all("a"):  # 去掉导语末尾的"[全文]"
                extra.decompose()
        spans = li.select(".module-interact span")
        out.add(
            title=_clean(a),
            url=url,
            desc=_clean(desc) or None,
            timestamp=_date_ms(_clean(spans[-1])) if spans else _url_date_ms(url),
        )
    return out.items


async def _get_guancha(board: str, no_cache: bool) -> _Fetch:
    # 首页新闻 / 要闻同用一份首页;首页的 li 嵌套不规范,必须 html.parser
    result = await _fetch_html(_GUANCHA, no_cache, f"{ROUTE_NAME}:guancha-home")
    html = _html(result)
    items = (
        _parse_guancha_top(html, _GUANCHA)
        if board == "guancha-top"
        else _parse_guancha_yaowen(html, _GUANCHA)
    )
    return *_meta(result), items


async def _get_guancha_shiping(no_cache: bool) -> _Fetch:
    result = await _fetch_html(_GUANCHA_SP, no_cache, f"{ROUTE_NAME}:guancha-shiping")
    return *_meta(result), _parse_guancha_shiping(_html(result), _GUANCHA_SP)


async def _get_guancha_intl(no_cache: bool) -> _Fetch:
    result = await _fetch_html(_GUANCHA_INTL, no_cache, f"{ROUTE_NAME}:guancha-intl")
    return *_meta(result), _parse_guancha_column(_html(result), _GUANCHA_INTL)


# ---------------------------------------------------------------- 环球网


async def _get_huanqiu(no_cache: bool) -> _Fetch:
    """环球网国际频道首页主信息流"最新消息":先取 /api/channel_pc 的栏目节点
    (国际滚动新闻、独家、图片、环视频),再请求 /api/list?node="…",…&offset=0&limit=24。"""
    channel = await _fetch(
        urljoin(_HUANQIU, "/api/channel_pc"),
        no_cache,
        f"{ROUTE_NAME}:huanqiu-world:channel",
        response_type="json",
    )
    payload = channel.data if isinstance(channel.data, dict) else {}
    root = next(iter((payload.get("children") or {}).values()), {})
    nodes: list[str] = []
    for child in (root.get("children") or {}).values():
        nodes.append(f'"{child["node"]}"')
        nodes.extend(f'"{c["node"]}"' for c in (child.get("children") or {}).values())
    if not nodes:
        raise RuntimeError(
            "huanqiu api/channel_pc has no channel nodes (page changed)"
        )
    list_url = (
        f"{urljoin(_HUANQIU, '/api/list')}"
        f"?node={quote(','.join(nodes), safe='/,')}&offset=0&limit=24"
    )
    result = await _fetch(
        list_url,
        no_cache,
        f"{ROUTE_NAME}:huanqiu-world",
        headers={"X-Requested-With": "XMLHttpRequest"},  # 页面组件带头,实测非必需,照带
        response_type="json",
    )
    rows = (result.data or {}).get("list") if isinstance(result.data, dict) else None
    out = _Collector()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("aid") or "")
        if not aid:
            continue  # 列表末尾有一个空对象
        kind = "gallery" if row.get("addltype") == "gallery" else "article"
        host = row.get("host") or urlsplit(_HUANQIU).hostname
        ctime = row.get("ctime")
        cover = row.get("cover")
        out.add(
            item_id=aid,
            title=str(row.get("title") or ""),
            url=f"https://{host}/{kind}/{aid}",
            desc=str(row.get("summary") or "").strip() or None,
            cover=urljoin("https:", str(cover)) if cover else None,
            timestamp=get_time(int(ctime)) if str(ctime or "").isdigit() else None,
        )
    return *_meta(result), out.items


# ---------------------------------------------------------------- 参考消息 / 凤凰网


async def _get_cankaoxiaoxi(no_cache: bool) -> _Fetch:
    """json/channel/yaowen/list.json:首页"要闻"模块(alias yaowen),文件原顺序。"""
    result = await _fetch(
        urljoin(_CKXX, "/json/channel/yaowen/list.json"),
        no_cache,
        f"{ROUTE_NAME}:cankaoxiaoxi-yaowen",
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    out = _Collector()
    for row in payload.get("list") or []:
        data = (
            row.get("data")
            if isinstance(row, dict) and isinstance(row.get("data"), dict)
            else {}
        )
        url = str(data.get("url") or data.get("otherUrl") or "").strip()
        out.add(
            item_id=str(data.get("id") or url),
            title=str(data.get("title") or ""),
            url=url,
            cover=data.get("mCoverImg") or data.get("mCoverImg_s") or None,
            author=str(data.get("author") or "").strip() or None,
            desc=str(data.get("description") or "").strip() or None,
            timestamp=_date_ms(data.get("publishTime") or data.get("lastpublishTime")),
        )
    return *_meta(result), out.items


async def _get_ifeng(no_cache: bool) -> _Fetch:
    """凤凰热榜页内嵌 ``var allData = {…}`` 的 content.list;链接用页面自己用的
    link.weburl(ishare 分享页)。"""
    result = await _fetch_html(_IFENG, no_cache, f"{ROUTE_NAME}:ifeng-hot")
    match = re.search(r"var\s+allData\s*=\s*(\{.*?\});\s*\n", _html(result), re.DOTALL)
    if not match:
        raise RuntimeError(
            "ifeng hotNewsRank page has no allData (page changed)"
        )
    rows = ((json.loads(match.group(1)).get("content") or {}).get("list")) or []
    out = _Collector()
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = row.get("link") if isinstance(row.get("link"), dict) else {}
        label = row.get("hotLabel") if isinstance(row.get("hotLabel"), dict) else {}
        url = str(link.get("weburl") or "").strip()
        out.add(
            item_id=str(row.get("documentId") or row.get("id") or url),
            title=str(row.get("title") or ""),
            url=url,
            cover=row.get("thumbnail") or None,
            hot=_hot(str(label.get("hotGrade") or "")),
        )
    return *_meta(result), out.items


# ---------------------------------------------------------------- 中国新闻周刊


def _parse_inewsweek(html: str, page: str, block: str) -> list[ListItem]:
    """中国新闻周刊首页(GBK):十大热文 div.sin_top10_cont li(h4 标题);
    首页推荐是"首页手动展示4条数据"的 div.grid-item(置顶 4 条 + 瀑布流首屏
    19 条,中间被注释掉的 ten_text 不算)。"""
    soup = _soup(html)
    out = _Collector()
    if block == "top10":
        for li in soup.select("div.sin_top10_cont li"):
            a = li.find("a", href=True)
            if isinstance(a, Tag):
                url = urljoin(page, str(a["href"]))
                out.add(
                    title=_clean(li.find("h4")),
                    url=url,
                    cover=_cover(li, page),
                    timestamp=_url_date_ms(url),
                )
    else:
        for item in soup.select("div.grid-item"):
            a = item.find("a", href=True)
            if isinstance(a, Tag):
                url = urljoin(page, str(a["href"]).strip())
                out.add(
                    title=_clean(item.find("p")),
                    url=url,
                    cover=_cover(item, page),
                    timestamp=_url_date_ms(url),
                )
    return out.items


async def _get_inewsweek(board: str, no_cache: bool) -> _Fetch:
    result = await _fetch_gbk_html(_INEWSWEEK, no_cache, f"{ROUTE_NAME}:{board}")
    items = _parse_inewsweek(_html(result), _INEWSWEEK, board.rsplit("-", 1)[1])
    return *_meta(result), items


# ---------------------------------------------------------------- China Daily


def _parse_epaper(html: str, page: str, day: date) -> list[ListItem]:
    """报纸电子版一天的全部版面文章:div.lft_art 的 newslist-bigtitle(带导语)
    与 newslist-common;timestamp 取出版日 0 点。"""
    soup = _soup(html)
    out = _Collector()
    publish_ms = _date_ms(f"{day:%Y-%m-%d}")
    for box in soup.select(
        "div.lft_art div.newslist-bigtitle, div.lft_art div.newslist-common"
    ):
        a = box.find("a", href=True)
        if isinstance(a, Tag):
            out.add(
                title=_clean(a),
                url=urljoin(page, str(a["href"])),
                desc=_clean(box.find("p")) or None,
                timestamp=publish_ms,
            )
    return out.items


async def _get_chinadaily_epaper(no_cache: bool) -> _Fetch:
    """入口 /china 301 到 2021-05-21(原站"最新"指向错误),从北京时间今天往前逐日
    找第一个有文章的日期;周日不出报(页面日历脚本的规则),跳过;最多回看 7 天。"""
    day = datetime.now(CHINA_TZ).date()
    for _ in range(8):
        if day.weekday() != 6:
            url = f"{_EPAPER}{day:%Y-%m}/{day:%d}"
            result: RequestResult | None = None
            try:
                result = await _fetch_html(url, no_cache)
            except Exception:  # noqa: BLE001 - 当天版面还没生成(404 等)时退到前一期
                result = None
            if result is not None and _html(result):
                items = _parse_epaper(_html(result), url, day)
                if items:
                    return *_meta(result), items
        day -= timedelta(days=1)
    raise RuntimeError("chinadaily epaper has no articles in the last 7 days")


def _parse_chinadaily_list(html: str, page: str) -> list[ListItem]:
    """China 频道 Latest 列表第 1 页:div.tw3_01_2,h4 标题、b 发布时间、配图。"""
    soup = _soup(html)
    out = _Collector()
    for box in soup.select("div.tw3_01_2"):
        a = box.select_one("h4 a[href]")
        if a is not None:
            out.add(
                title=_clean(a),
                url=urljoin(page, str(a["href"])),
                cover=_cover(box, page),
                timestamp=_date_ms(_clean(box.find("b"))),
            )
    return out.items


async def _get_chinadaily_china(no_cache: bool) -> _Fetch:
    result = await _fetch_html(
        _CHINADAILY_CHINA, no_cache, f"{ROUTE_NAME}:chinadaily-china"
    )
    return *_meta(result), _parse_chinadaily_list(_html(result), _CHINADAILY_CHINA)


# ---------------------------------------------------------------- 央广网 / 中国科技网 / 南风窗


def _drop_sign(url: str) -> str:
    """央广网部分链接带 TRS 内容管理系统的预览参数 ?sign=…(解码是
    trs_wcm_preview_access),不是文章地址的一部分,去掉。"""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "sign"
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _parse_cnr(html: str, page: str) -> list[ListItem]:
    """央广网滚动新闻(GBK)第 1 页:div.articleList > div.item,strong 标题、
    em 摘要、span.publishTime 时间(每页 10 条)。"""
    soup = _soup(html)
    out = _Collector()
    for item in soup.select("div.articleList div.item"):
        a = item.find("a", href=True)
        if isinstance(a, Tag):
            out.add(
                title=_clean(item.find("strong")),
                url=_drop_sign(urljoin(page, str(a["href"]))),
                desc=_clean(item.find("em")) or None,
                cover=_cover(item, page),
                timestamp=_date_ms(_clean(item.select_one(".publishTime"))),
            )
    return out.items


async def _get_cnr(no_cache: bool) -> _Fetch:
    result = await _fetch_gbk_html(_CNR, no_cache, f"{ROUTE_NAME}:cnr-roll")
    return *_meta(result), _parse_cnr(_html(result), _CNR)


def _parse_stdaily(html: str, page: str) -> list[ListItem]:
    """中国科技网"滚动"node_324.html 第 1 页:div.f_lieb_list > dl,h3 标题、
    dt 配图、dd p 摘要、.sourthTime 来源与时间。"""
    soup = _soup(html)
    out = _Collector()
    for dl in soup.select("div.f_lieb_list > dl"):
        a = dl.select_one("h3 a[href]")
        if a is None:
            continue
        spans = dl.select(".sourthTime span")
        out.add(
            title=_clean(a),
            url=urljoin(page, str(a["href"])),
            cover=_cover(dl.find("dt"), page),
            desc=_clean(dl.select_one("dd p")) or None,
            timestamp=_date_ms(_clean(spans[-1])) if spans else None,
        )
    return out.items


async def _get_stdaily(no_cache: bool) -> _Fetch:
    result = await _fetch_html(_STDAILY, no_cache, f"{ROUTE_NAME}:stdaily-roll")
    return *_meta(result), _parse_stdaily(_html(result), _STDAILY)


def _parse_nfcmag(html: str, page: str) -> list[ListItem]:
    """南风窗首页:各栏目推荐块(div.comBox)里的 li,h5.title 标题、p 导语;
    按页面顺序,同一篇只留一次。页面上没有文章日期。"""
    soup = _soup(html)
    out = _Collector()
    for li in soup.select("div.comBox li"):
        a = li.select_one("h5.title a[href]")
        if a is not None:
            out.add(
                title=_clean(a),
                url=urljoin(page, str(a["href"])),
                desc=_clean(li.find("p")) or None,
            )
    return out.items


async def _get_nfcmag(no_cache: bool) -> _Fetch:
    result = await _fetch_html(_NFCMAG, no_cache, f"{ROUTE_NAME}:nfcmag-home")
    return *_meta(result), _parse_nfcmag(_html(result), _NFCMAG)


# ---------------------------------------------------------------- 求是


def _parse_qstheory_headline(html: str, page: str) -> list[ListItem]:
    """求是网首页"头条"区 div.headtitle(样式表注释"头条 headtitle"):
    大标题 .content + 相关链接 .more li;同一链接只留一次。"""
    box = _soup(html).select_one("div.headtitle")
    if box is None:
        raise RuntimeError(
            "qstheory home has no div.headtitle (page changed)"
        )
    out = _Collector()
    for a in box.select(".content a[href], .more a[href]"):
        url = urljoin(page, str(a["href"]))
        out.add(title=_clean(a), url=url, timestamp=_url_date_ms(url))
    return out.items


async def _get_qstheory_headline(no_cache: bool) -> _Fetch:
    result = await _fetch_html(
        _QSTHEORY, no_cache, f"{ROUTE_NAME}:qstheory-headline"
    )
    return *_meta(result), _parse_qstheory_headline(_html(result), _QSTHEORY)


async def _get_qstheory_issue(no_cache: bool) -> _Fetch:
    """《求是》最新一期目录:首页"往期"块的数据文件 ds_32929c18….json 第 1 行是
    最新一期的目录页,目录页 #detailContent 里每个 <p> 一篇:"标题 /作者"。"""
    result = await _fetch(
        urljoin(_QSTHEORY, _QSTHEORY_DS),
        no_cache,
        f"{ROUTE_NAME}:qstheory-issue:ds",
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("datasource") or []
    toc = str((rows[0] if rows else {}).get("publishUrl") or "")
    if not toc:
        raise RuntimeError(
            "qstheory issue datasource has no toc url (page changed)"
        )
    toc_url = urljoin(_QSTHEORY, toc)
    page = await _fetch_html(toc_url, no_cache)
    body = _soup(_html(page)).select_one("#detailContent")
    if body is None:
        raise RuntimeError(
            f"qstheory toc page has no #detailContent: {toc}"
        )
    out = _Collector()
    for p in body.find_all("p"):
        a = p.find("a", href=True)
        text = _clean(p)
        if not isinstance(a, Tag) or not text:
            continue
        title, _, author = text.rpartition(" /") if " /" in text else (text, "", "")
        url = urljoin(toc, str(a["href"]))
        out.add(
            title=title,
            url=url,
            author=" ".join(author.split()) or None,
            timestamp=_url_date_ms(url),
        )
    return *_meta(result), out.items


_FETCHERS: dict[str, Any] = {
    "guancha-yaowen": _get_guancha,
    "guancha-top": _get_guancha,
    "guancha-shiping": lambda board, no_cache: _get_guancha_shiping(no_cache),
    "guancha-intl": lambda board, no_cache: _get_guancha_intl(no_cache),
    "huanqiu-world": lambda board, no_cache: _get_huanqiu(no_cache),
    "cankaoxiaoxi-yaowen": lambda board, no_cache: _get_cankaoxiaoxi(no_cache),
    "ifeng-hot": lambda board, no_cache: _get_ifeng(no_cache),
    "inewsweek-top10": _get_inewsweek,
    "inewsweek-rec": _get_inewsweek,
    "chinadaily-epaper": lambda board, no_cache: _get_chinadaily_epaper(no_cache),
    "chinadaily-china": lambda board, no_cache: _get_chinadaily_china(no_cache),
    "cnr-roll": lambda board, no_cache: _get_cnr(no_cache),
    "stdaily-roll": lambda board, no_cache: _get_stdaily(no_cache),
    "nfcmag-home": lambda board, no_cache: _get_nfcmag(no_cache),
    "qstheory-headline": lambda board, no_cache: _get_qstheory_headline(no_cache),
    "qstheory-issue": lambda board, no_cache: _get_qstheory_issue(no_cache),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    from_cache, update_time, items = await _FETCHERS[board](board, no_cache)
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"{ROUTE_NAME} board '{board}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(items),
        fromCache=from_cache,
        updateTime=update_time,
        data=items,
    )
