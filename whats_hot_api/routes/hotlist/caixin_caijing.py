"""财新网与财经网(caixin.com / caijing.com.cn,公开、无签名、无 cookie)。

board_api 单元 `tmp/board_api/caixin_caijing` 的 1:1 迁移,证据见该目录 README 与
`verify/param_matrix.md`、`verify/home_blocks_check.md`、`verify/top3_check.md`。7 个子榜:

- 首页推荐 `caixin-home`:www.caixin.com 首页(服务端渲染)照 HTML 顺序取三块——
  头条 `div.toutiao_box`(左栏 `dl`、图片轮播 `#zyqh dl`、右栏专题频道文章 `dl`;
  `div.entry02` 是专题落地页入口,不算)→ 图片列表头条 `div.img_list_box li`
  (`em` 小标进 desc、`p a` 是标题)→ 新闻主体 `div.news_list` 直接子节点
  (文章 `dl`、图集 `div.news_img_box`;广告位 `div.index-ad-o` 不算),按文章 id 去重。
  条目只认财新文章页链接 `/YYYY-MM-DD/<id>.html`(含图集、视频、周刊、专题频道文章页)
- 最新文章 `caixin-latest`:滚动新闻页(Vue 客户端渲染)调用的
  `gateway.caixin.com/api/dataplatform/scroll/index?page=1&size=20&date=&channel=0`
  (页面脚本 size 固定 20,频道表第 1 项"全部滚动"是 channel 0),业务壳 code=0
- 政经 / 经济 / 金融频道要闻 `caixin-china` / `caixin-economy` / `caixin-finance`:
  频道要闻页"加载更多"的 JSONP `gateway.caixin.com/api/extapi/homeInterface.jsp?
  subject=<id>&type=0&count=25&picdim=_266_177&start=0`(政经 100300241、经济 100300184、
  金融 100300177),第 1 页与要闻页首屏 25 条逐条相同(top3_check 实测),去掉 `cb(...)`
  包装再解析。tophub 这三个节点停在 2015-12,原站要闻页仍在更新,照原站
- 国际新闻世界频道 `caixin-world`:tophub 节点抓的是停在 2013 年的旧页
  (`international.caixin.com/news/` 现在是"备用要闻"),按榜名取现在的世界频道首页:
  头条区 `div.topNews`(1 条)在前、要闻"全部"tab `#container_0 div.boxa`(9 条)在后,
  按 id 去重
- 财经精选 `caijing-selected`:yuanchuang.caijing.com.cn 列表页(标题"财经精选_")
  `li > div.wzbt a`,一页 20 条;日期取 `div.time`(只有日期,北京时间 0 点),原站给 http 链接

请求头口径(param_matrix 实测):全部接口与页面不挑请求头,唯独 homeInterface 对
`python-httpx` 的缺省 UA 返回 200 空响应(0 字节),所以该接口显式带浏览器 UA;
滚动新闻接口照页面带上 Referer(不带也是同一份),其余不带多余头。
署名清理口径:"文｜财新 曾佳 发自美国首都华盛顿,王晶 发自北京" → "财新 曾佳,王晶"。
首页"09月30日 19:59"没有年份,以页面生成时间(响应 Date 头减 Age)为基准取北京时间
当年,比它晚一天以上的算去年(跨年)。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "caixin-caijing"

# type 声明序第一个(caixin-home)是默认榜。
type_map: dict[str, str] = {
    "caixin-home": "财新网 · 首页推荐",
    "caixin-latest": "财新网 · 最新文章",
    "caixin-china": "财新网 · 政经频道要闻",
    "caixin-economy": "财新网 · 经济频道要闻",
    "caixin-finance": "财新网 · 金融频道要闻",
    "caixin-world": "财新网 · 国际新闻世界频道",
    "caijing-selected": "财经网 · 财经精选",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "财新网与财经网",
    "description": (
        "财新网首页推荐、最新文章(滚动新闻)、政经 / 经济 / 金融频道要闻、世界频道要闻;财经网财经精选"
    ),
    "link": "https://www.caixin.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_DEFAULT_TYPE = next(iter(type_map))
_HOME_URL = "https://www.caixin.com/"
_WORLD_URL = "https://international.caixin.com/"
_CAIJING_URL = "https://yuanchuang.caijing.com.cn/"
_SCROLL_URL = "https://gateway.caixin.com/api/dataplatform/scroll/index?page=1&size=20&date=&channel=0"
_NEWS_PAGE_SIZE = 25  # 要闻页 loadMore 的 size;第 2 页 start=25
_SUBJECTS = {
    "caixin-china": ("100300241", "https://china.caixin.com/news/"),
    "caixin-economy": ("100300184", "https://economy.caixin.com/news/"),
    "caixin-finance": ("100300177", "https://finance.caixin.com/news/"),
}

# homeInterface 对 python-httpx 的缺省 UA 返回 200 空响应(param_matrix 实测);
# 浏览器 UA、curl 缺省 UA、空 UA 都正常,照项目惯例显式带浏览器 UA。
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_JSON_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
}
_HTML_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_BEIJING = timezone(timedelta(hours=8))
# 财新文章页链接(含图集 photos、视频 video、周刊 weekly、手机版 /m/、专题频道 topics 下的正文页);
# 专题落地页、广告位不是这个形态,自然被排除。
_ARTICLE_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/(\d+)\.html")
_CAIJING_RE = re.compile(r"/(\d{4})/(\d{2})(\d{2})/(\d+)\.shtml")
_CAIJING_DATE_RE = re.compile(r"(\d{4})年(\d{2})月(\d{2})日")
_MD_TIME_RE = re.compile(r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}:\d{2})")
_CN_TIME_RE = re.compile(r"(\d{4})年(\d{2})月(\d{2})日\s*(\d{1,2}:\d{2})?")
_AUTHOR_PREFIX_RE = re.compile(r"^\s*文\s*[｜|]\s*")
_DATILINE_RE = re.compile(r"\s*发自[^，,、]*")


def _subject_url(subject: str) -> str:
    # 与要闻页 loadMore 的拼法一致(jQuery 的 callback=? 换成固定回调名 cb)
    return (
        "https://gateway.caixin.com/api/extapi/homeInterface.jsp"
        f"?callback=cb&subject={subject}&type=0&count={_NEWS_PAGE_SIZE}&picdim=_266_177&start=0"
    )


def _page_time(headers: dict[str, Any]) -> datetime:
    """页面生成时间 = 响应 Date 头减 Age;没有 Date 头时用当前时间(北京时间)。

    首页"MM月DD日 HH:MM"没有年份,以它为基准取当年、跨年按去年(证据口径)。
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


def _beijing_seconds(value: str, fmt: str) -> int | None:
    try:
        return int(datetime.strptime(value.strip(), fmt).replace(tzinfo=_BEIJING).timestamp())
    except ValueError:
        return None


def _month_day_seconds(match: re.Match[str], now: datetime) -> int | None:
    """`09月30日 19:59`(没有年份)→ Unix 秒:取北京时间当年,比页面生成时间晚一天以上算去年。"""
    month, day, clock = int(match.group(1)), int(match.group(2)), match.group(3)
    for year in (now.year, now.year - 1):
        seconds = _beijing_seconds(f"{year}-{month:02d}-{day:02d} {clock}", "%Y-%m-%d %H:%M")
        if seconds is not None and seconds <= int(now.timestamp()) + 86400:
            return seconds
    return None


def clean_author(text: str | None) -> str | None:
    """"文｜财新 曾佳 发自美国首都华盛顿,王晶 发自北京" → "财新 曾佳,王晶"。"""
    if not text:
        return None
    cleaned = _AUTHOR_PREFIX_RE.sub("", text)
    cleaned = _DATILINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,，")
    return cleaned or None


def strip_jsonp(text: str) -> Any:
    """去掉 JSONP 回调包装 `cb({...})`(回调包装前有十几个换行)再解析;纯 JSON 原样解析。"""
    match = re.match(r"^\s*[\w$.]+\s*\((.*)\)\s*;?\s*$", text, re.DOTALL)
    return json.loads(match.group(1) if match else text)


def _text(node: Any) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else ""


def _img_url(node: Any) -> str | None:
    if not isinstance(node, Tag):
        return None
    return str(node.get("data-src") or node.get("src") or "").strip() or None


def _home_units(soup: BeautifulSoup) -> list[tuple[str, Tag]]:
    """首页三块的条目单元,照 HTML 顺序:(块名, 节点)。

    - 头条 `div.toutiao_box`(原站注释"头条 begin"):左栏两条 `dl`、中间图片轮播 `#zyqh dl`、
      右栏专题入口图 `div.entry02`(取出来是为了跳过它)与频道文章 `dl`
    - 图片列表头条 `div.img_list_box`("图片列表头条 begin"):`li`
    - 新闻主体 `div.news_list`("新闻主体 begin"):直接子节点 `dl`(文章)、
      `div.news_img_box`(图集)、`div.index-ad-o`(广告位,取出来是为了跳过它)
    """
    units: list[tuple[str, Tag]] = []
    top = soup.select_one("div.toutiao_box")
    if isinstance(top, Tag):
        units += [("头条", node) for node in top.select("dl, div.entry02")]
    img_list = soup.select_one("div.img_list_box")
    if isinstance(img_list, Tag):
        units += [("图片列表头条", node) for node in img_list.select("li")]
    box = soup.select_one("div.news_list")
    if not isinstance(box, Tag):
        raise RuntimeError("Caixin home page has no div.news_list (page structure changed)")  # noqa: TRY004 - 上游结构漂移不是类型契约问题
    units += [("新闻主体", node) for node in box.find_all(["dl", "div"], recursive=False) if isinstance(node, Tag)]
    return units


def _home_fields(block: str, node: Tag) -> tuple[Tag | None, Tag | None, Tag | None, str]:
    """一个单元 → (标题链接, 作者时间 span, 封面 img, 小标)。广告位、专题入口图没有文字链接,返回 (None, …)。"""
    classes = node.get("class") or []
    if block == "新闻主体":
        if node.name == "dl":
            return node.select_one("dd p a[href]"), node.select_one("dd > span"), node.select_one("dt img"), ""
        if "news_img_box" in classes:  # 图集条目:标题在 .tit p a,时间在直接子级的 span
            return node.select_one("div.tit p a[href]"), node.find("span", recursive=False), node.select_one("ul img"), ""
        return None, None, None, ""  # 广告位 index-ad-o 等
    if block == "图片列表头条":  # `em` 是标题上方的小标(如"最新封面报道"),`p` 是标题
        return node.select_one("p a[href]"), None, node.select_one("span img"), _text(node.select_one("em"))
    # 头条区:左右栏 dt a + dd span(署名 时间);轮播 span>a>img + div.wzdf a(标题);专题入口图只有图片链接
    anchor = node.select_one("dt a[href]") or node.select_one("div.wzdf a[href]")
    return anchor, node.select_one("dd span"), node.select_one("span img"), ""


def parse_home(page_html: str, now: datetime) -> list[ListItem]:
    """首页推荐:照页面顺序输出 头条 → 图片列表头条 → 新闻主体 里的文章,按文章 id 去重。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for block, node in _home_units(BeautifulSoup(page_html, "lxml")):
        anchor, span, img, kicker = _home_fields(block, node)
        if not isinstance(anchor, Tag):
            continue
        url = str(anchor["href"]).strip()
        match = _ARTICLE_RE.search(url)
        title = _text(anchor)
        if not match or not title or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        meta = _text(span)
        time_match = _MD_TIME_RE.search(meta)
        items.append(
            ListItem(
                id=match.group(2),
                title=title,
                url=url,
                cover=_img_url(img),
                # 轮播、右栏、图片列表头条没有时间与署名,留空
                author=clean_author(meta[: time_match.start()]) if time_match else None,
                desc=kicker or None,
                timestamp=get_time(_month_day_seconds(time_match, now)) if time_match else None,
            )
        )
    return items


def parse_scroll(payload: Any) -> list[ListItem]:
    """最新文章:滚动新闻接口,业务壳 code=0;articleList 照接口顺序输出,time 毫秒。"""
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError(f"Caixin scroll api returned an unexpected payload: {str(payload)[:200]}")
    items: list[ListItem] = []
    for row in (payload.get("data") or {}).get("articleList") or []:
        if not isinstance(row, dict) or not row.get("contentId") or not row.get("url"):
            continue
        items.append(
            ListItem(
                id=str(row["contentId"]),
                title=str(row.get("title") or "").strip(),
                url=str(row["url"]),
                cover=row.get("picture") or None,
                author=clean_author(row.get("author")),
                desc=row.get("summary") or None,
                timestamp=get_time(row.get("time")),
            )
        )
    return items


def parse_subject(payload: Any) -> list[ListItem]:
    """频道要闻:homeInterface 的 `datas` 照接口顺序输出(= 要闻页首屏顺序),time 北京时间。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("datas"), list):
        raise RuntimeError(f"Caixin homeInterface returned an unexpected payload: {str(payload)[:200]}")  # noqa: TRY004 - 上游结构漂移不是类型契约问题
    items: list[ListItem] = []
    for row in payload["datas"]:
        if not isinstance(row, dict) or not row.get("nid") or not row.get("link"):
            continue
        imgs = (row.get("pict") or {}).get("imgs") or []
        cover = imgs[0].get("url") if imgs and isinstance(imgs[0], dict) else None
        items.append(
            ListItem(
                id=str(row["nid"]),
                title=str(row.get("desc") or "").strip(),
                url=str(row["link"]),
                cover=cover or None,
                author=clean_author((row.get("edit") or {}).get("name")),
                desc=row.get("summ") or None,
                timestamp=get_time(_beijing_seconds(str(row.get("time") or ""), "%Y-%m-%d %H:%M:%S")),
            )
        )
    return items


def parse_world(page_html: str) -> list[ListItem]:
    """世界频道要闻:头条区 `div.topNews`(1 条)在前,要闻"全部"tab `#container_0 div.boxa` 在后。"""
    soup = BeautifulSoup(page_html, "lxml")
    nodes: list[tuple[Any, Any, Any, Any]] = []
    top = soup.select_one("div.topNews")
    if isinstance(top, Tag):  # 频道首页最上方的大图头条,页面上在要闻列表之前
        nodes.append(
            (top.select_one("h3 a[href]"), top.select_one("div.txt > span"), top.select_one("div.pic img"), top.select_one("div.txt > p"))
        )
    for box in soup.select("#container_0 div.boxa"):
        nodes.append(
            (box.select_one("h4 a[href]"), box.find("span", recursive=False), box.select_one("div.pic img"), box.find("p", recursive=False))
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for anchor, span, img, lead in nodes:
        if not isinstance(anchor, Tag):
            continue
        url = str(anchor["href"])
        match = _ARTICLE_RE.search(url)
        title = _text(anchor)
        if not match or not title or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        meta = _text(span)
        time_match = _CN_TIME_RE.search(meta)
        seconds = None
        if time_match:
            seconds = _beijing_seconds(
                f"{time_match.group(1)}-{time_match.group(2)}-{time_match.group(3)} {time_match.group(4) or '00:00'}",
                "%Y-%m-%d %H:%M",
            )
        items.append(
            ListItem(
                id=match.group(2),
                title=title,
                url=url,
                cover=_img_url(img),
                author=clean_author(meta[: time_match.start()]) if time_match else None,
                desc=_text(lead) or None,
                timestamp=get_time(seconds),
            )
        )
    return items


def parse_caijing(page_html: str) -> list[ListItem]:
    """财经精选:`li > div.wzbt a`;日期取 div.time(与链接 /YYYY/MMDD/ 一致),北京时间 0 点。

    原站给的 http 链接照原样输出(证据口径,不做改写)。
    """
    items: list[ListItem] = []
    for li in BeautifulSoup(page_html, "lxml").select("li"):
        anchor = li.select_one("div.wzbt a[href]")
        if not isinstance(anchor, Tag):
            continue
        url = str(anchor["href"])
        match = _CAIJING_RE.search(url)
        title = _text(anchor)
        if not match or not title:
            continue
        listed = _CAIJING_DATE_RE.search(_text(li.select_one("div.time")))
        if listed:
            date_text = f"{listed.group(1)}-{listed.group(2)}-{listed.group(3)}"
        else:  # 列表日期缺失时取链接里的日期
            date_text = "-".join(match.groups()[:3])
        items.append(
            ListItem(
                id=match.group(4),
                title=title,
                url=url,
                author=_text(li.select_one("div.author")) or None,
                desc=_text(li.select_one("div.subtitle")) or None,
                timestamp=get_time(_beijing_seconds(date_text, "%Y-%m-%d")),
            )
        )
    return items


async def _fetch_html(url: str, no_cache: bool) -> RequestResult:
    return await get(url=url, headers=_HTML_HEADERS, no_cache=no_cache, response_type="text", origin_info=True)


def _unwrap(result: RequestResult) -> tuple[str, datetime]:
    wrapped = result.data if isinstance(result.data, dict) else {}
    return str(wrapped.get("data") or ""), _page_time(wrapped.get("headers") or {})


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", _DEFAULT_TYPE)
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")

    if type_param == "caixin-latest":
        result = await get(url=_SCROLL_URL, headers=_JSON_HEADERS, no_cache=no_cache, response_type="json")
        data = parse_scroll(result.data)
    elif type_param in _SUBJECTS:
        subject, referer = _SUBJECTS[type_param]
        result = await get(
            url=_subject_url(subject),
            headers={**_JSON_HEADERS, "Referer": referer},
            no_cache=no_cache,
            response_type="text",
        )
        body = str(result.data or "")
        if not body.strip():
            # homeInterface 对 python-httpx 缺省 UA 返回 200 空响应(param_matrix 实测)
            raise RuntimeError(
                "Caixin homeInterface returned an empty 200 response; "
                "check User-Agent (python-httpx default UA is filtered)"
            )
        data = parse_subject(strip_jsonp(body))
    elif type_param == "caixin-home":
        result = await _fetch_html(_HOME_URL, no_cache)
        html, now = _unwrap(result)
        data = parse_home(html, now)
    elif type_param == "caixin-world":
        result = await _fetch_html(_WORLD_URL, no_cache)
        html, _ = _unwrap(result)
        data = parse_world(html)
    else:
        result = await _fetch_html(_CAIJING_URL, no_cache)
        html, _ = _unwrap(result)
        data = parse_caijing(html)

    if not data:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"Caixin board '{type_param}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
