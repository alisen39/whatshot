"""半月谈栏目(www.banyuetan.org,公开、无签名、无 cookie、不需要任何请求头)。

迁移自 board_api ``tmp/board_api/banyuetan_channels`` 单元(12 个已完成榜;
区域风采、改革创新、脱贫攻坚 3 个栏目已停更,不做,证据见该目录 README)。
只有 http(https 连不上,``verify/https_check.txt``)。

- 11 个栏目:栏目页第 1 页 ``div.bty_tbtj_list.js-tbtj ul > li``(h3>a 标题、p 导语、
  span.tag3 日期、img 配图),照原站顺序;列表前有本栏目首屏轮播
  (``div.first_screen > div.dyp_lbt``,时政讲解、文化)时先输出轮播再接列表,
  只取链接目录与本栏目列表相同的条目(今日谈的轮播是全站头条,不取);
  去重两步,都保留先出现的:先按 id,再把标题相同且发布日期相同的后一条去掉
  (原站会把同一篇文章分别发到轮播节点和列表节点,两个 id、正文逐字相同)
- 要闻TOP10:栏目页右侧"要闻top10"区块(每个栏目页都相同),标题被原站截成
  以".."结尾;按链接取同页要闻列表的完整标题,补不全的再取 1 次首页
  (文字或 title 属性,必须以截断的前半段开头才用),仍补不到的照区块原样,
  message 写明条数
- 发布时间:页面只显示到日(与链接里 /detail/YYYYMMDD/ 逐条核对,对不上留空),
  取该日北京时间 0 点;链接长串数字里嵌的 10 位时间与列表日期有出入,不用
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import CHINA_TZ, get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "banyuetan-channels"

BASE = "http://www.banyuetan.org/"
HOME = BASE  # 首页:要闻TOP10 里不在要闻列表的截断标题(全站头条 /dyp/ 稿)从这里补全

# 子榜键 -> (中文名, 栏目目录)。top10 取要闻栏目页右侧的"要闻top10"区块。
# 声明序第一个是默认榜(board_api 的 DEFAULT_TYPE=top10)。
_BOARDS: dict[str, tuple[str, str]] = {
    "top10": ("要闻TOP10", "yaowen"),
    "jinritan": ("今日谈", "jinritan"),
    "shizhengjiangjie": ("时政讲解", "shizhengjiangjie"),
    "pinglun": ("评论", "banyuetanpinglun"),
    "difangguancha": ("地方观察", "difangguancha"),
    "jicengzhili": ("基层治理", "jicengzhili"),
    "minshenghuati": ("民生话题", "minshenghuati"),
    "guoji": ("国际", "guoji"),
    "wenhua": ("文化", "wenhua"),
    "keji": ("科技", "keji"),
    "jiankang": ("健康", "jiankang"),
    "qiyezixun": ("企业资讯", "qiyezixun"),
}

_TYPE_MAP: dict[str, str] = {key: board[0] for key, board in _BOARDS.items()}

_DEFAULT_TYPE = next(iter(_TYPE_MAP))

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "半月谈",
    "description": (
        "半月谈网栏目:要闻TOP10、今日谈、时政讲解、评论、地方观察、基层治理、"
        "民生话题、国际、文化、科技、健康、企业资讯"
    ),
    "link": BASE,
    "params": {"type": {"name": "栏目", "type": _TYPE_MAP}},
}

# 文章链接:/jrt/detail/20260924/1000200033134991790214224290782358_1.html
_DETAIL = re.compile(r"/detail/(\d{4})(\d{2})(\d{2})/(\d+)_\d+\.html")
_TRUNCATED = ".."  # 要闻top10 区块把长标题截成"前半段.."


def source_url(path_type: str) -> str:
    return f"{BASE}byt/{_BOARDS[path_type][1]}/index.html"


def _clean(node: Tag | None) -> str:
    # 原站标题、导语开头偶尔带零宽空格(U+200B),\s 不含它,单独去掉首尾的
    if node is None:
        return ""
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return text.strip("\u200b\ufeff").strip()


def _item_id(url: str) -> str:
    match = _DETAIL.search(url)
    return match.group(4) if match else url


def _dir(url: str) -> str:
    """链接的栏目目录:http://www.banyuetan.org/szjj/detail/… → szjj。"""
    parts = urlsplit(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else ""


def _timestamp_ms(url: str, shown: str = "") -> int | None:
    """列表日期"2026-09-24"(没有就用链接里的日期)→ 该日北京时间 0 点的毫秒;
    两者对不上时留空。"""
    match = _DETAIL.search(url)
    ymd = (
        (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None
    )
    shown_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", shown.strip())
    if shown_match:
        shown_ymd = (
            int(shown_match.group(1)),
            int(shown_match.group(2)),
            int(shown_match.group(3)),
        )
        if ymd and shown_ymd != ymd:
            return None
        ymd = shown_ymd
    if not ymd:
        return None
    try:
        dt = datetime(*ymd, tzinfo=CHINA_TZ)
    except ValueError:
        return None
    return get_time(int(dt.timestamp()))


def _is_http_abs(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _parse_list(box: Tag, page_url: str) -> list[ListItem]:
    """栏目列表(列表模式)div.bty_tbtj_list.js-tbtj ul > li。卡片模式
    div.bty_tbtj_list_card 是同一批条目、同一顺序,不重复取。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for li in box.select("ul > li"):
        a = li.select_one("h3 a[href]")
        if not isinstance(a, Tag):
            continue
        url = urljoin(page_url, str(a.get("href") or "").strip())
        title = _clean(a)
        if not title or url in seen:
            continue
        seen.add(url)
        img = li.select_one("img[src]")
        cover = str(img.get("src") or "").strip() if isinstance(img, Tag) else ""
        items.append(
            ListItem(
                id=_item_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                cover=cover if _is_http_abs(cover) else None,
                desc=_clean(li.select_one("p")) or None,
                timestamp=_timestamp_ms(url, _clean(li.select_one("span.tag3"))),
            )
        )
    return items


def _parse_carousel(
    soup: BeautifulSoup, page_url: str, column_dir: str, listed: dict[str, ListItem]
) -> list[ListItem]:
    """栏目首屏轮播 div.first_screen > div.dyp_lbt 的 div.event-item:
    div.banner_title a(显示的标题、链接)、a.banner_img img(配图)。
    只留链接目录等于本栏目列表目录的条目;同一篇也在列表里时,导语、列表日期取列表那条。"""
    items: list[ListItem] = []
    for ev in soup.select("div.first_screen > div.dyp_lbt div.event-item"):
        a = ev.select_one("div.banner_title a[href]") or ev.select_one("a.banner_img[href]")
        if not isinstance(a, Tag):
            continue
        url = urljoin(page_url, str(a.get("href") or "").strip())
        title = _clean(a) or str(a.get("title") or "").strip()
        if not title or _dir(url) != column_dir:
            continue
        img = ev.select_one("img[src]")
        cover = str(img.get("src") or "").strip() if isinstance(img, Tag) else ""
        same = listed.get(_item_id(url))
        items.append(
            ListItem(
                id=_item_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                cover=(
                    cover if _is_http_abs(cover) else (same.cover if same else None)
                ),
                desc=same.desc if same else None,
                timestamp=same.timestamp if same else _timestamp_ms(url),
            )
        )
    return items


def parse_column(html: str, page_url: str) -> list[ListItem]:
    """栏目页:列表前有本栏目首屏轮播(时政讲解、文化)时先输出轮播,再接列表。
    去重两步,都只留第一次出现:先按 id;再按(标题, 发布日期)——同一篇文章发在
    轮播、列表两个节点时 id 不同,标题与日期相同(轮播条目没有导语时借用列表那条的)。"""
    soup = BeautifulSoup(html, "lxml")
    box = soup.select_one("div.bty_tbtj_list.js-tbtj")
    if not isinstance(box, Tag):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误
            "banyuetan column page has no list div.bty_tbtj_list.js-tbtj (page changed)"
        )
    listed = _parse_list(box, page_url)
    # 本栏目列表的链接目录:列表里出现最多的那个(少数条目是别的栏目挂过来的稿)
    dirs = Counter(_dir(item.url) for item in listed)
    column_dir = dirs.most_common(1)[0][0] if dirs else ""
    by_id = {item.id: item for item in listed}
    items: list[ListItem] = []
    seen: set[str] = set()
    by_key: dict[tuple[str, int | None], int] = {}  # (标题, 发布日期) -> items 里的下标
    for item in _parse_carousel(soup, page_url, column_dir, by_id) + listed:
        key = (item.title, item.timestamp)
        if item.id in seen:
            continue
        if key in by_key:
            # 同一篇的另一个节点:去掉;保留的轮播条目没有导语时借用列表那条的
            kept = items[by_key[key]]
            if not kept.desc and item.desc:
                items[by_key[key]] = kept.model_copy(update={"desc": item.desc})
            continue
        seen.add(item.id)
        by_key[key] = len(items)
        items.append(item)
    return items


def parse_top10(html: str, page_url: str) -> list[ListItem]:
    """右侧"要闻top10":ul.title2_box li a.special1,名次就是顺序。标题被截成
    以".."结尾,用同页要闻列表按链接补全;补不到的保留截断标题,由 handle_route
    再用首页补。"""
    soup = BeautifulSoup(html, "lxml")
    full: dict[str, str] = {}
    for li in soup.select("div.byt_tbtj_list_card ul > li, div.bty_tbtj_list.js-tbtj ul > li"):
        a = li.select_one("h3 a[href]")
        if isinstance(a, Tag) and _clean(a):
            full.setdefault(urljoin(page_url, str(a.get("href") or "").strip()), _clean(a))
    items: list[ListItem] = []
    seen: set[str] = set()
    for a in soup.select("ul.title2_box li a.special1[href]"):
        url = urljoin(page_url, str(a.get("href") or "").strip())
        title = full.get(url) or _clean(a)
        if not title or url in seen:
            continue
        seen.add(url)
        items.append(
            ListItem(
                id=_item_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                timestamp=_timestamp_ms(url),
            )
        )
    return items


def complete_titles(items: list[ListItem], html: str, page_url: str) -> list[ListItem]:
    """用首页(头条、轮播、要闻焦点区等)的链接补全仍被截断的标题:
    同一链接的文字或 title 属性,且以截断的前半段开头才用。"""
    soup = BeautifulSoup(html, "lxml")
    candidates: dict[str, list[str]] = {}
    for a in soup.select("a[href]"):
        url = urljoin(page_url, str(a.get("href") or "").strip())
        for text in (_clean(a), str(a.get("title") or "").strip()):
            if text and not text.endswith(_TRUNCATED):
                candidates.setdefault(url, []).append(text)
    out: list[ListItem] = []
    for item in items:
        prefix = (
            item.title[: -len(_TRUNCATED)].strip() if item.title.endswith(_TRUNCATED) else ""
        )
        match = next(
            (t for t in candidates.get(item.url, []) if prefix and t.startswith(prefix)),
            None,
        )
        out.append(item.model_copy(update={"title": match}) if match else item)
    return out


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", _DEFAULT_TYPE)
    if board_type not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")

    name = _BOARDS[board_type][0]
    url = source_url(board_type)
    message: str | None = None
    result = await get(
        url=url, no_cache=no_cache, response_type="text", cache_key=f"{ROUTE_NAME}:{board_type}"
    )
    html = result.data if isinstance(result.data, str) else ""
    items = parse_top10(html, url) if board_type == "top10" else parse_column(html, url)
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"banyuetan board '{board_type}' parsed no items: {url}")

    if board_type == "top10" and any(item.title.endswith(_TRUNCATED) for item in items):
        # 区块里的截断标题在要闻列表补不全时,再取 1 次首页补全(全站头条 /dyp/ 稿)
        home_html = ""
        try:
            home = await get(
                url=HOME, no_cache=no_cache, response_type="text", cache_key=f"{ROUTE_NAME}:home"
            )
            if isinstance(home.data, str):
                home_html = home.data
        except Exception:  # noqa: BLE001 - 首页取不到只是补不全,照区块原样
            home_html = ""
        if home_html:
            items = complete_titles(items, home_html, HOME)
        left = sum(1 for item in items if item.title.endswith(_TRUNCATED))
        if left:
            message = f"{left} 条标题在要闻列表和首页都没找到完整标题,照区块原样(截断的)"

    return RouterData(
        **ROUTE_META,
        type=name,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
        message=message,
    )
