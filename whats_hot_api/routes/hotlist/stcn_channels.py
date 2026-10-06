"""证券时报网栏目(www.stcn.com,公开、无签名、无 cookie)。

board_api 单元 `tmp/board_api/stcn_channels` 的 1:1 迁移,证据见该目录 README 与
`verify/header_matrix.md`、`verify/top3_check.md`。21 个子榜:

- 19 个栏目:服务端渲染的列表页 `/article/list/<栏目>.html`,取页面直出的一页
  (`ul.infinite-list` 的 10 条;浏览器里 common.js 的 infinite() 会再取下一页,不算)。
  7 个栏目(company/gsxw/gsdt/cj/fund/finance/comment)的列表上方有"栏目头条"区块
  (`.top-news-box`,2 条),照原站页面顺序放在最前;区块标题在列表页被截断,
  再取这 2 篇文章页拿完整标题、来源作者与发布时间(取不到时退回列表页截断标题)。
  区块左侧轮播图是广告跳转 `ad/track.html`、条目下的关键词是站内搜索链接,都不算条目
- 快讯(人民财讯):页面客户端渲染,数据来自 `/article/list.html?type=kx`(JSON,30 条);
  排序照页面脚本 new-quick-news-list.js:按 time 倒序、置顶(isTop)在前,广告位(isAdd)不输出
- 人民财讯热榜:快讯页右栏"换一换"的数据 `/article/category-news-rank.html?type=kx`
  (JSON,10 条,首次加载不带 refresh;没有时间,`hot` 是"热"角标布尔值,不是热度)

请求头口径(header_matrix 实测):列表页不需要任何请求头;快讯接口必须带
`X-Requested-With: XMLHttpRequest`,否则返回快讯页整页 HTML;热榜接口不需要,照页面
jQuery 请求一致带上;Referer/UA 都不需要(项目缺省 UA 直接通过)。
时间口径:列表时间只到分钟、没有年份(今天 `HH:MM`、今年 `MM-DD HH:MM`,北京时间),
以页面生成时间(响应 Date 头减 Age,见 _page_time)为基准补日期与年份,跨年时按去年;
文章页与快讯是完整时间;热榜没有时间。
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "stcn-channels"

WWW = "https://www.stcn.com"
# 子榜键与原站栏目代码一致,声明序第一个(yw)是默认榜。
LIST_BOARDS: dict[str, str] = {
    "yw": "要闻",
    "gd": "滚动新闻",
    "company": "公司",
    "gsxw": "公司新闻",
    "gsdt": "公司动态",
    "cj": "产经",
    "gs": "股市",
    "gsyl": "股市一览",
    "djjd": "独家解读",
    "fund": "基金",
    "finance": "金融",
    "comment": "评论",
    "kcb": "科创板",
    "xsb": "新三板",
    "ct": "创投",
    "zk": "ESG",
    "data": "智能资讯",
    "djsj": "数据资讯",
    "tjkt": "投教",
}
# 有"栏目头条"区块的 7 个栏目(公司 / 公司新闻 / 公司动态三页共用同一个区块)。
TOP_NEWS_CODES = frozenset({"company", "gsxw", "gsdt", "cj", "fund", "finance", "comment"})
KX_TYPE, KX_LABEL = "kx", "快讯"
KX_RANK_TYPE, KX_RANK_LABEL = "kx-rank", "人民财讯热榜"

type_map: dict[str, str] = {
    "yw": "要闻",
    "gd": "滚动新闻",
    KX_TYPE: KX_LABEL,
    KX_RANK_TYPE: KX_RANK_LABEL,
    **LIST_BOARDS,
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "证券时报网",
    "description": (
        "证券时报网栏目列表:要闻、滚动、快讯(人民财讯)、人民财讯热榜、公司、产经、"
        "股市、基金、金融、评论、科创板、新三板、创投、ESG、数据、投教等"
    ),
    "link": WWW + "/",
    "params": {
        "type": {
            "name": "栏目",
            "type": type_map,
        },
    },
}

_DEFAULT_TYPE = next(iter(type_map))
_LIST_URL = WWW + "/article/list/{code}.html"
_KX_URL = WWW + "/article/list.html?type=kx"
_KX_RANK_URL = WWW + "/article/category-news-rank.html?type=kx"
# 快讯接口不带 X-Requested-With 时返回快讯页整页 HTML(header_matrix 实测);
# 两个 JSON 接口都照页面 jQuery $.getJSON 一致带上 XHR 头。
_XHR_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": WWW + "/article/list/kx.html",
}
_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_BEIJING = timezone(timedelta(hours=8))
_ARTICLE_ID_RE = re.compile(r"/article/detail/(\d+)\.html")
_VIDEO_ID_RE = re.compile(r"/live/video-detail/(\d+)\.html")
_TIME_TEXT_RE = re.compile(r"(\d{4}-)?(\d{1,2}-\d{1,2} )?\d{1,2}:\d{2}(:\d{2})?")
_BIDI_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def _page_time(headers: dict[str, Any]) -> datetime:
    """页面生成时间 = 响应 Date 头减 Age(没有 Age 就是 Date);没有 Date 头时用当前时间。

    列表页的"今天 HH:MM / 今年 MM-DD HH:MM"以它为换算基准(board_api 证据口径,
    不用本机当前时间)。headers 来自共享 get(origin_info=True)返回的响应头。
    """
    lower = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    try:
        base = parsedate_to_datetime(lower["date"]).astimezone(_BEIJING)
    except (KeyError, TypeError, ValueError):
        return datetime.now(_BEIJING)
    try:
        age = int(lower.get("age") or 0)
    except ValueError:
        age = 0
    return base - timedelta(seconds=max(age, 0))


def _clean(value: Any) -> str:
    """去标签、去原站个别标题里混入的不可见方向控制符(如 U+202C),收敛空白。"""
    text = _html.unescape(_BIDI_RE.sub("", re.sub(r"<[^>]+>", "", str(value or ""))))
    return re.sub(r"\s+", " ", text).strip()


def _item_id(url: str) -> str:
    """文章用 `/article/detail/<id>.html` 的 id;投教课堂的视频条目记 `video-<编号>`。"""
    match = _ARTICLE_ID_RE.search(url)
    if match:
        return match.group(1)
    match = _VIDEO_ID_RE.search(url)
    return f"video-{match.group(1)}" if match else url


def _parse_page_time(text: str, now: datetime) -> int | None:
    """列表页时间(北京时间)→ Unix 秒:今天 `HH:MM`、今年 `MM-DD HH:MM`、更早带年份。

    "今天 / 今年"相对页面生成时间 now;跨年时 1 月看到的 `12-31` 按去年算。
    """
    text = text.strip()
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            moment = datetime.strptime(f"{now:%Y-%m-%d} {text}", "%Y-%m-%d %H:%M").replace(tzinfo=_BEIJING)
        elif re.fullmatch(r"\d{1,2}-\d{1,2} \d{1,2}:\d{2}", text):
            moment = datetime.strptime(f"{now.year}-{text}", "%Y-%m-%d %H:%M").replace(tzinfo=_BEIJING)
            if moment > now + timedelta(days=1):
                moment = moment.replace(year=now.year - 1)
        elif re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}(:\d{2})?", text):
            moment = datetime.strptime(text[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_BEIJING)
        else:
            return None
    except ValueError:
        return None
    return int(moment.timestamp())


def _is_time(text: str) -> bool:
    """区分 `.info span` 里的时间与来源 / 作者(时间只到分钟,可能带日期与秒)。"""
    return bool(_TIME_TEXT_RE.fullmatch(text.strip()))


def _parse_list_li(li: Tag, now: datetime) -> ListItem | None:
    anchor = li.select_one(".tt a")
    if anchor is None or not anchor.get("href"):
        return None
    url = urljoin(WWW, str(anchor["href"]))
    title = _clean(anchor.get_text(" "))
    if not title:
        return None
    spans = [span.get_text(" ", strip=True) for span in li.select(".info span")]
    spans = [span for span in spans if span]
    # 最后一个 span 是时间;其余按页面顺序是来源与作者(空格连接)。
    stamp = _parse_page_time(spans[-1], now) if spans and _is_time(spans[-1]) else None
    byline = [span for span in spans if not _is_time(span)]
    summary = li.select_one(".text")
    cover = li.select_one("img")
    return ListItem(
        id=_item_id(url),
        title=title,
        url=url,
        cover=urljoin(WWW, str(cover["src"])) if cover is not None and cover.get("src") else None,
        author=" ".join(byline) or None,
        desc=_clean(summary.get_text(" ")) if summary is not None else None,
        timestamp=get_time(stamp),
    )


def _parse_list_page(page_html: str, now: datetime) -> tuple[list[tuple[str, str]], list[ListItem]]:
    """返回(栏目头条区块的 [(链接, 页面截断标题)], 列表条目)。

    轮播图(`ad/track.html` 广告跳转)与关键词标签(`search.html?keyword=`)不取。
    """
    soup = BeautifulSoup(page_html, "lxml")
    tops = [
        (urljoin(WWW, str(anchor["href"])), anchor.get_text(" ", strip=True))
        for anchor in soup.select(".list-page-left-top .top-news-box .top-news .top a[href]")
    ]
    listing = soup.select_one("ul.infinite-list")
    if listing is None:
        raise RuntimeError("STCN list page has no ul.infinite-list (page structure changed)")
    items = [
        item
        for li in listing.find_all("li", recursive=False)
        if isinstance(li, Tag) and (item := _parse_list_li(li, now))
    ]
    return tops, items


def _parse_detail(url: str, page_html: str, now: datetime) -> ListItem | None:
    """文章页:完整标题(.detail-title)、来源 / 作者与发布时间(.detail-info)。"""
    soup = BeautifulSoup(page_html, "lxml")
    title_el = soup.select_one(".detail-title")
    title = _clean(title_el.get_text(" ")) if title_el is not None else ""
    if not title:
        return None
    info = [span.get_text(" ", strip=True) for span in soup.select(".detail-info > span")]
    stamp = next((_parse_page_time(span, now) for span in info if _is_time(span)), None)
    byline = [re.sub(r"^(来源|作者)：", "", span) for span in info if span.startswith(("来源：", "作者："))]
    return ListItem(
        id=_item_id(url),
        title=title,
        url=url,
        author=" ".join(part for part in byline if part) or None,
        timestamp=get_time(stamp),
    )


def _parse_kx(rows: list[dict[str, Any]]) -> list[ListItem]:
    """快讯:照页面脚本 new-quick-news-list.js 排序——按 time 倒序、置顶(isTop)在前(两次稳定排序);
    广告位(isAdd)不算条目。show_time 是秒级,统一转毫秒。"""
    rows = [row for row in rows if isinstance(row, dict) and not row.get("isAdd")]
    rows = sorted(rows, key=lambda row: row.get("time") or 0, reverse=True)
    rows = sorted(rows, key=lambda row: 1 if row.get("isTop") else 0, reverse=True)
    items: list[ListItem] = []
    for row in rows:
        url = urljoin(WWW, str(row.get("url") or row.get("web_url") or ""))
        title = _clean(row.get("title"))
        if not title or url == WWW:
            continue
        images = row.get("images") if isinstance(row.get("images"), list) else []
        cover = images[0].get("src") if images and isinstance(images[0], dict) else None
        items.append(
            ListItem(
                id=str(row.get("id") or _item_id(url)),
                title=title,
                url=url,
                cover=cover,
                author=_clean(row.get("source")) or None,
                desc=_clean(row.get("content")) or None,
                timestamp=get_time(row.get("show_time")),
            )
        )
    return items


def _parse_rank(rows: list[dict[str, Any]]) -> list[ListItem]:
    """人民财讯热榜:接口没有时间;`hot` 是"热"角标布尔值,不是热度,不映射。"""
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = urljoin(WWW, str(row.get("url") or ""))
        title = _clean(row.get("title"))
        if title and url != WWW:
            items.append(ListItem(id=_item_id(url), title=title, url=url))
    return items


async def _fetch_json_board(url: str, no_cache: bool) -> tuple[RequestResult, list[dict[str, Any]]]:
    """两个 JSON 接口的业务壳:state=1 才是成功;不带 XHR 头时返回整页 HTML,json 解析即失败。"""
    result = await get(url=url, headers=_XHR_HEADERS, no_cache=no_cache, response_type="json")
    payload = result.data
    if not isinstance(payload, dict) or payload.get("state") != 1 or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"STCN api returned an unexpected payload: {str(payload)[:200]}")
    return result, payload["data"]


async def _top_news_item(url: str, fallback_title: str, no_cache: bool) -> ListItem:
    """栏目头条的文章页:完整标题与发布时间;取不到时退回列表页上的截断标题(证据口径)。"""
    item: ListItem | None = None
    try:
        result = await get(url=url, headers=_HTML_HEADERS, no_cache=no_cache, response_type="text")
        page_html = result.data if isinstance(result.data, str) else ""
        # 文章页时间是完整的 YYYY-MM-DD HH:MM,不依赖相对时间基准
        item = _parse_detail(url, page_html, datetime.now(_BEIJING))
    except Exception:  # noqa: BLE001 - 单篇文章页失效只降级标题,不拖垮整个栏目
        item = None
    if item is None and fallback_title:
        item = ListItem(id=_item_id(url), title=fallback_title.rstrip(".…").strip(), url=url)
    if item is None:
        raise RuntimeError(f"STCN top-news detail has no title: {url}")
    return item


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", _DEFAULT_TYPE)
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")

    if type_param == KX_TYPE:
        result, data_rows = await _fetch_json_board(_KX_URL, no_cache)
        data, label = _parse_kx(data_rows), KX_LABEL
    elif type_param == KX_RANK_TYPE:
        result, data_rows = await _fetch_json_board(_KX_RANK_URL, no_cache)
        data, label = _parse_rank(data_rows), KX_RANK_LABEL
    else:
        result = await get(
            url=_LIST_URL.format(code=type_param),
            headers=_HTML_HEADERS,
            no_cache=no_cache,
            response_type="text",
            origin_info=True,
        )
        wrapped = result.data if isinstance(result.data, dict) else {}
        now = _page_time(wrapped.get("headers") or {})
        top_links, items = _parse_list_page(str(wrapped.get("data") or ""), now)
        tops = (
            [await _top_news_item(url, short, no_cache) for url, short in top_links]
            if type_param in TOP_NEWS_CODES
            else []
        )
        data = []
        seen: set[str] = set()
        for item in tops + items:  # 照原站页面顺序:栏目头条在最前,按链接去重
            if item.url in seen:
                continue
            seen.add(item.url)
            data.append(item)
        label = LIST_BOARDS[type_param]

    if not data:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"STCN board '{type_param}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
