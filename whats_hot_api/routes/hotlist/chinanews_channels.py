"""中新网栏目(www.chinanews.com.cn,公开、无签名、无 cookie,请求头非必需)。

board_api 单元 `tmp/board_api/chinanews_channels` 的 1:1 迁移,证据见该目录 README
与 `analysis_report.md`、`verify/header_check.txt`。16 个子榜:

- 12 个官方 RSS `rss/<频道>.xml`(RSS 目录页 /rss/ 列出,频道标题与 tophub 榜名一致,
  每个 30 条、生活 12 条),保留 feed 原顺序(要闻导读是编辑顺序,其余按时间倒序);
  item 没有 guid,id 取 link
- 国内新闻:国内新闻滚动页 `china.shtml`(200 条);滚动即时新闻:滚动新闻第 1 页
  `scroll-news/news1.html`(100 条,含视频稿)。两页都是服务端渲染的 `.content_list li`
- 中新热榜、热门图片、热门视频:首页右栏三个区块(各 10 条,服务端渲染),按
  div.lmtitle 标题文字定位,标题取 a 的 title 属性(链接文字被截成"…")
- 时政新闻(china.xml)与国内新闻(china.shtml)、即时新闻(scroll-news.xml)与滚动
  即时新闻(news1.html)是同源榜:RSS 是同一列表的另一地址(即时 RSS 滤掉多数视频稿),
  按 board_api 证据各自一个子榜

字段口径:
- id/url:文章绝对地址(相对、协议相对地址按主站补全);链接里没有 /年/月-日/ 的
  (频道页自身这类导航链接)不算条目
- timestamp:RSS 取 pubDate(+0800);滚动页取地址里的年月日加 .dd_time 的时:分
  (北京时间,页面只写"9-27 22:20"不带年);首页区块只有地址里的日期,取北京时间当天 0 点
- desc:仅 RSS 有(item/description 去 HTML,前 500 字);页面列表不提供
- hot/cover/author:feed 与页面列表都不提供
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "chinanews-channels"

WWW = "https://www.chinanews.com.cn/"

# 子榜键 -> (中文名, 取数方式, 参数)。rss:feed 文件名;page:滚动列表页路径;
# home:首页区块标题。声明序第一个是默认榜。
_BOARDS: dict[str, tuple[str, str, str]] = {
    "hot": ("中新热榜", "home", "中新热榜"),
    "photo-hot": ("热门图片", "home", "热门图片"),
    "video-hot": ("热门视频", "home", "热门视频"),
    "importnews": ("要闻导读", "rss", "importnews"),
    "scroll": ("滚动即时新闻", "page", "scroll-news/news1.html"),
    "scroll-rss": ("即时新闻", "rss", "scroll-news"),
    "china": ("国内新闻", "page", "china.shtml"),
    "china-rss": ("时政新闻", "rss", "china"),
    "world": ("国际新闻", "rss", "world"),
    "society": ("社会新闻", "rss", "society"),
    "finance": ("财经新闻", "rss", "finance"),
    "life": ("健康·生活", "rss", "life"),
    "dwq": ("大湾区", "rss", "dwq"),
    "chinese": ("华人新闻", "rss", "chinese"),
    "culture": ("文化新闻", "rss", "culture"),
    "sports": ("体育新闻", "rss", "sports"),
}

type_map: dict[str, str] = {key: board[0] for key, board in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "中国新闻网",
    "description": (
        "中新网栏目:首页中新热榜、热门图片、热门视频,滚动即时新闻、国内新闻滚动,"
        "以及要闻、时政、国际、社会、财经、生活、大湾区、华人、文化、体育等官方 RSS。"
    ),
    "link": WWW,
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_DEFAULT_TYPE = next(iter(type_map))
_BEIJING = timezone(timedelta(hours=8))
# 文章地址里的日期:/gn/2026/09-27/10704546.shtml、/tp/hd2011/2026/09-27/1206069.shtml、
# /sh/shipin/cns/2026/09-27/news1070333.shtml
_URL_DATE = re.compile(r"/(20\d{2})/(\d{2})-(\d{2})/")
# 滚动页 .dd_time:"9-27 22:20"(不带年)
_CLOCK = re.compile(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")
_DESC_MAX_CHARS = 500

# header_check 实测浏览器 UA / curl UA / 无 UA / python-httpx UA 都返回 200 且字节数相同,
# 请求头非必需;这里照 board_api 公共缺省口径带浏览器 UA
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}


def _board_url(board_type: str) -> str:
    _name, kind, arg = _BOARDS[board_type]
    if kind == "rss":
        return f"{WWW}rss/{arg}.xml"
    if kind == "page":
        return WWW + arg
    return WWW


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_article(url: str) -> bool:
    """文章地址都带 /年/月-日/;不带的是频道页自身这类导航链接,不算条目。"""
    return bool(_URL_DATE.search(url))


def _url_date(url: str) -> tuple[int, int, int] | None:
    match = _URL_DATE.search(url)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _timestamp_from_url(url: str, clock: str = "") -> int | None:
    """北京时间 -> 毫秒。年月日取文章地址;时分取 .dd_time 的"9-27 22:20"(月日与地址
    对得上才用,否则当天 0 点);地址里没有日期返回 None。"""
    ymd = _url_date(url)
    if ymd is None:
        return None
    hour = minute = 0
    match = _CLOCK.search(clock)
    if match and (int(match.group(1)), int(match.group(2))) == ymd[1:]:
        hour, minute = int(match.group(3)), int(match.group(4))
    try:
        dt = datetime(*ymd, hour, minute, tzinfo=_BEIJING)
    except ValueError:
        return None
    return get_time(int(dt.timestamp()))


def _article_id(url: str) -> str:
    """board_api 口径:id 是文章绝对地址。"""
    return url


def _rss_description(raw: str) -> str | None:
    """item/description 去 HTML,前 500 字。"""
    text = _clean_text(BeautifulSoup(raw or "", "lxml").get_text(" ", strip=True))
    return text[:_DESC_MAX_CHARS] or None


def _dedupe(items: list[ListItem]) -> list[ListItem]:
    """同一链接在一个列表里出现两次只留第一次。"""
    seen: set[str] = set()
    out: list[ListItem] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            out.append(item)
    return out


def _item_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return _clean_text(node.text or "") if node is not None else ""


def _parse_rss(xml_text: str) -> list[ListItem]:
    """官方 RSS:item 只有 title/link/description/pubDate,没有 guid,id 取 link;
    保留 feed 原顺序;过滤指向频道页自身的条目。"""
    root = ET.fromstring(xml_text)
    items: list[ListItem] = []
    for item in root.findall("./channel/item"):
        url = _item_text(item, "link")
        title = _item_text(item, "title")
        if not url or not title or not _is_article(url):
            continue
        pub_date = _item_text(item, "pubDate")
        timestamp: int | None = None
        if pub_date:
            try:
                timestamp = get_time(int(parsedate_to_datetime(pub_date).timestamp()))
            except (TypeError, ValueError, OverflowError):
                timestamp = None
        items.append(
            ListItem(
                id=_article_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                desc=_rss_description(item.findtext("description") or ""),
                timestamp=timestamp,
            )
        )
    return _dedupe(items)


def _parse_scroll_page(html: str, page_url: str) -> list[ListItem]:
    """滚动列表页(.content_list li):.dd_lm 栏目、.dd_bt a 标题链接、
    .dd_time "月-日 时:分";空 li(分隔线)跳过。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    for li in soup.select(".content_list li"):
        anchor = li.select_one(".dd_bt a[href]")
        if not isinstance(anchor, Tag):
            continue
        url = urljoin(page_url, str(anchor.get("href") or "").strip())
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title or not _is_article(url):
            continue
        time_node = li.select_one(".dd_time")
        clock = _clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
        items.append(
            ListItem(
                id=_article_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                timestamp=_timestamp_from_url(url, clock),
            )
        )
    return _dedupe(items)


def _parse_home_block(html: str, block: str) -> list[ListItem]:
    """首页右栏区块:标题 div.lmtitle(文字为"中新热榜 / 热门图片 / 热门视频")后面
    第一个 div.rdph-list2 里的 li>a。链接文字被截成"…",完整标题在 a 的 title 属性;
    时间只有地址里的日期,取北京时间当天 0 点。"""
    soup = BeautifulSoup(html, "lxml")
    head = next(
        (node for node in soup.select("div.lmtitle") if node.get_text(strip=True) == block),
        None,
    )
    box = head.find_next_sibling("div", class_="rdph-list2") if head is not None else None
    if not isinstance(box, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误
            f"chinanews home page has no '{block}' block (page structure changed)"
        )
    items: list[ListItem] = []
    for anchor in box.select("li a[href]"):
        if not isinstance(anchor, Tag):
            continue
        url = urljoin(WWW, str(anchor.get("href") or "").strip())
        title = _clean_text(str(anchor.get("title") or "") or anchor.get_text(" ", strip=True))
        if not title or not _is_article(url):
            continue
        items.append(
            ListItem(
                id=_article_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                timestamp=_timestamp_from_url(url),
            )
        )
    return _dedupe(items)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", _DEFAULT_TYPE)
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    label, kind, _arg = _BOARDS[board_type]
    url = _board_url(board_type)

    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text")
    html = result.data if isinstance(result.data, str) else ""
    if kind == "rss":
        items = _parse_rss(html)
    elif kind == "page":
        items = _parse_scroll_page(html, url)
    else:
        items = _parse_home_block(html, label)
    if not items:
        # 错误页 / 业务错误壳 / 空解析不静默降级为空榜
        raise RuntimeError(f"chinanews board '{board_type}' parsed no items: {url}")

    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
