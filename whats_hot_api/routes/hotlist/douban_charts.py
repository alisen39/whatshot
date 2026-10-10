"""豆瓣书影音榜（douban-charts）：27 个豆瓣书影音子榜，单路由 type 区分。

移植自 board_api/douban_charts（2026-09-27 已验证，verify/ 下有自验、全量核对与推翻性验证）：
- 移动端 rexxar 接口 m.douban.com/rexxar/api/v2（只要求 Referer 非空）：subject_collection/{ID}/items
  （口碑榜、实时热门、影院热映、近期热门剧集、单曲 / 新碟、非虚构图书）、skynet/new_playlists
  （找当月"定档热门新剧 / 电影推荐"片单 ID）、chart/hot_search_board（实时热门讨论）、
  gallery/web_hot_topics（话题广场热门话题）、subject/recent_hot/tv（原站"选剧集"页的最近热门剧集）
- movie.douban.com 服务端渲染页面：/chart（北美票房榜）、/cinema/later/beijing/（即将上映）、
  /cinema/nowplaying/beijing/（正在上映，只取"正在上映"区块，不混入同页"即将上映"）
- www.douban.com：/feed/review/movie（最受欢迎的影评 RSS，保持原站顺序）、/gallery/all（全部话题第一页）

反爬口径（verify/header_matrix.jsonl、verify/adversarial_review.md）：
- rexxar 必须 Referer 非空（不带 400 invalid_request_1284），UA 值不限
- www.douban.com 必须带 User-Agent（不带 403）
- UA 黑名单：python-requests / python-httpx 默认 UA 一律 418，全部请求统一带浏览器 UA
- 豆瓣对频率敏感：同站点（各子域算一个站）两次请求至少隔 2.1 秒
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import CHINA_TZ, get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "douban-charts"

# 子榜键 -> (中文名, 取数方式, 参数)。rexxar 榜单的子榜键就是榜单 ID 把下划线换成短横线；
# 声明序第一个（movie-weekly-best）是默认榜。
_BOARDS: dict[str, tuple[str, str, str]] = {
    "movie-weekly-best": ("一周口碑榜", "collection", "movie_weekly_best"),
    "tv-global-best-weekly": ("全球口碑剧集榜", "collection", "tv_global_best_weekly"),
    "tv-chinese-best-weekly": ("华语口碑剧集榜", "collection", "tv_chinese_best_weekly"),
    "show-chinese-best-weekly": ("国内口碑综艺榜", "collection", "show_chinese_best_weekly"),
    "show-global-best-weekly": ("国外口碑综艺榜", "collection", "show_global_best_weekly"),
    "subject-real-time-hotest": ("实时热门书影音", "collection", "subject_real_time_hotest"),
    "tv-real-time-hotest": ("实时热门电视", "collection", "tv_real_time_hotest"),
    "movie-showing": ("影院热映", "collection", "movie_showing"),
    "tv-animation": ("近期热门动画", "collection", "tv_animation"),
    "tv-domestic": ("近期热门国产剧", "collection", "tv_domestic"),
    "tv-japanese": ("近期热门日剧", "collection", "tv_japanese"),
    "tv-american": ("近期热门美剧", "collection", "tv_american"),
    "tv-korean": ("近期热门韩剧", "collection", "tv_korean"),
    "music-single": ("热门单曲榜", "collection", "music_single"),
    "music-chinese": ("华语新碟榜", "collection", "music_chinese"),
    "book-nonfiction": ("热门图书-非虚构类", "collection", "book_nonfiction"),
    "monthly-tv": ("本月热门新剧推荐", "monthly", "tv"),
    "monthly-movie": ("本月热门电影推荐", "monthly", "movie"),
    "us-box-office": ("北美票房榜", "box_office", ""),
    "movie-later": ("即将上映的电影", "later", ""),
    "nowplaying": ("正在上映的电影", "nowplaying", "0"),
    "tv-hot": ("热门剧集排行榜", "recent_hot", "tv"),
    "tv-us": ("热门美剧", "recent_hot", "tv_american"),
    "review-best": ("最受欢迎的影评", "review_feed", ""),
    "hot-search-board": ("实时热门讨论", "hot_search", ""),
    "gallery-hot-topics": ("热门话题（话题广场）", "web_hot_topics", ""),
    "gallery-all-topics": ("热门话题（全部话题）", "gallery_all", ""),
}

type_map: dict[str, str] = {key: label for key, (label, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "豆瓣",
    "description": "豆瓣书影音榜单：口碑榜、实时热门、热映 / 即将上映、票房、剧集、音乐、图书、影评、话题",
    "link": "https://www.douban.com",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = "movie-weekly-best"
REXXAR = "https://m.douban.com/rexxar/api/v2"
PAGE_SIZE = 50  # rexxar 榜单每页条数：服务端单页上限 50（count=100 也只回 50 条），超过要翻页
MAX_ITEMS = 200  # whatshot --limit 的上限
CITY = "beijing"  # 热映 / 即将上映按城市出片，固定北京（RSSHub 同款默认值）
# 原站现行"选剧集"页 movie.douban.com/tv/ 的"最近热门剧集"：rexxar subject/recent_hot/tv，
# type 是页签（tv 综合、tv_american 欧美剧……），前端每次加载 limit=20
RECENT_HOT_PAGE = 20
RECENT_HOT_TABS = {"tv": "综合", "tv_american": "欧美剧"}

# 豆瓣 UA 黑名单：python-requests / python-httpx 默认 UA 返回 418（推翻性验证），
# www.douban.com 不带 UA 403，所以全部请求统一带浏览器 UA。
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# 豆瓣对频率敏感：同一站点（豆瓣各子域算一个站）两次请求至少隔 2.1 秒
# （board_api 采集全程 2 秒 1 个请求，没有遇到 403 或验证页）。
_MIN_SPACING_SECONDS = 2.1
_spacing_lock = asyncio.Lock()
_last_request_at = float("-inf")


class _FetchMeta:
    """跨请求聚合 fromCache / updateTime（一个子榜可能发多个上游请求）。"""

    __slots__ = ("from_cache", "update_time")

    def __init__(self) -> None:
        self.from_cache = True
        self.update_time = ""

    def observe(self, result: RequestResult) -> None:
        self.from_cache = self.from_cache and result.from_cache
        self.update_time = result.update_time or self.update_time


async def _throttle() -> None:
    global _last_request_at
    async with _spacing_lock:
        wait = _MIN_SPACING_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


async def _fetch(
    url: str,
    *,
    referer: str | None = None,
    params: dict[str, Any] | None = None,
    no_cache: bool = False,
    response_type: str = "json",
) -> RequestResult:
    """带站点级间隔的 GET；非 200 由共享 http_client 抛 HTTPStatusError。"""
    await _throttle()
    headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    return await get(
        url=url,
        headers=headers,
        params=params,
        no_cache=no_cache,
        response_type=response_type,
    )


async def _fetch_json(
    url: str,
    meta: _FetchMeta,
    *,
    referer: str | None = None,
    params: dict[str, Any] | None = None,
    no_cache: bool = False,
) -> dict[str, Any]:
    result = await _fetch(url, referer=referer, params=params, no_cache=no_cache)
    meta.observe(result)
    if not isinstance(result.data, dict):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"douban {url} returned {type(result.data).__name__} instead of a JSON object "
            "(login page or feed changed)"
        )
    return result.data


async def _fetch_text(url: str, meta: _FetchMeta, *, no_cache: bool = False) -> str:
    result = await _fetch(url, no_cache=no_cache, response_type="text")
    meta.observe(result)
    return str(result.data)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _number(text: str) -> int | None:
    """'13987人想看' -> 13987，'1.1万次浏览' -> 11000，'6000万' -> 60000000；取不到返回 None。"""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|亿)?", text.replace(",", ""))
    if not match:
        return None
    unit = {"万": 10_000, "亿": 100_000_000}.get(match.group(2) or "", 1)
    return round(float(match.group(1)) * unit)


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _join(*parts: object, limit: int = 500) -> str | None:
    text = " · ".join(str(part).strip() for part in parts if part and str(part).strip())
    return text[:limit] or None


def _subject_links(kind: str, sid: str, fallback: object) -> tuple[str, str | None]:
    """条目的 PC / 移动端链接。rexxar 给的 url 多是 App 分发页（doubanapp/dispatch），换成站点详情页。"""
    site = {"movie": "movie", "tv": "movie", "music": "music", "book": "book"}.get(kind)
    fallback_url = fallback if isinstance(fallback, str) and fallback else None
    if site:
        return (
            f"https://{site}.douban.com/subject/{sid}/",
            f"https://m.douban.com/{site}/subject/{sid}/",
        )
    return (
        fallback_url or f"https://www.douban.com/doubanapp/dispatch/{kind}/{sid}",
        fallback_url,
    )


def _cover_of(row: dict[str, Any]) -> str | None:
    """海报 / 封面：cover_url → cover.url → pic.normal（按榜不同，取第一个有的）。"""
    candidates = (
        row.get("cover_url"),
        row.get("cover").get("url") if isinstance(row.get("cover"), dict) else None,
        row.get("pic").get("normal") if isinstance(row.get("pic"), dict) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _subject_item(row: dict[str, Any], *, hot_is_heat: bool) -> ListItem | None:
    sid = str(row.get("id") or "")
    title = str(row.get("title") or "").strip()
    if not sid or not title:
        return None
    kind = str(row.get("type") or row.get("subtype") or "movie")
    url, mobile = _subject_links(kind, sid, row.get("url") or row.get("sharing_url"))
    rating = row.get("rating") if isinstance(row.get("rating"), dict) else {}
    value = rating.get("value") or 0
    score = f"评分 {value:.1f}" if value else (row.get("null_rating_reason") or None)
    cover = _cover_of(row)
    names = row.get("singer") if kind == "music" else row.get("author") if kind == "book" else None
    blurb = row.get("description") or row.get("comment") or ""
    # 推荐语不再并进 desc 回退链:两者都有时推荐语单列
    reason = str(row.get("recommended_reason") or "").strip() or None
    # 荣誉头衔(榜单名/年度榜单等)逐字保留,可有多枚
    badges = [
        {"text": str(honor.get("title") or "").strip()}
        for honor in row.get("honor_infos") or []
        if isinstance(honor, dict) and str(honor.get("title") or "").strip()
    ]
    metrics: dict[str, int] = {}
    rank_value = row.get("rank_value")
    if isinstance(rank_value, int) and not isinstance(rank_value, bool) and rank_value > 0:
        metrics["rankValue"] = rank_value
    rank = row.get("rank")
    # 实时热门榜的 score 是热度值；其余榜没有热度，用评价人数（与 douban-movie 的口径一致）
    hot = row.get("score") if hot_is_heat else (rating.get("count") or None)
    return ListItem(
        id=sid,
        title=title,
        url=url,
        mobileUrl=mobile,
        hot=hot,
        cover=cover,
        author=" / ".join(names) if isinstance(names, list) and names else None,
        desc=_join(score, row.get("card_subtitle") or row.get("info"), str(blurb)[:300]),
        badges=badges,
        metrics=metrics or None,
        sourceRank=rank if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 else None,
        recommendationReason=reason if blurb and reason else None,
    )


def _short(page: list[Any], total: int, start: int) -> bool:
    """这一页比应有的条数少（total=0 的空页也算）。"""
    return not page or len(page) < min(PAGE_SIZE, total - start)


async def _fetch_collection(
    cid: str, no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    """按 total 翻页取完整个榜单。
    实测偶发残缺响应（total=0 空页、条目明显少于 total），页不满时隔 2 秒重取一次。"""
    referer = f"https://m.douban.com/subject_collection/{cid}"
    collection_meta: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    start, total = 0, None
    while total is None or start < min(total, MAX_ITEMS):
        url = f"{REXXAR}/subject_collection/{cid}/items"
        params: dict[str, Any] = {"start": start, "count": PAGE_SIZE}
        payload = await _fetch_json(url, meta, referer=referer, params=params, no_cache=no_cache)
        page = payload.get("subject_collection_items") or []
        if not isinstance(page, list):
            raise RuntimeError(  # noqa: TRY004 - upstream shape problem
            f"douban {url} response subject_collection_items is not a list"
        )
        if _short(page, _as_int(payload.get("total")), start):
            payload = await _fetch_json(
                url, meta, referer=referer, params=params, no_cache=no_cache
            )
            page = payload.get("subject_collection_items") or []
        collection_meta = (
            payload.get("subject_collection")
            if isinstance(payload.get("subject_collection"), dict)
            else collection_meta
        )
        total = _as_int(payload.get("total"))
        rows += page
        if not page:
            break
        start += len(page)
    heat = cid.endswith("real_time_hotest")
    items = [item for item in (_subject_item(row, hot_is_heat=heat) for row in rows) if item]
    note = _join(
        collection_meta.get("name"),
        collection_meta.get("description"),
        collection_meta.get("updated_at") and f"更新于 {collection_meta['updated_at']}",
    )
    return items, note, f"https://m.douban.com/subject_collection/{cid}"


async def _fetch_monthly(
    subject_type: str, no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    """当月"定档热门新剧 / 电影推荐"片单：先在 skynet/new_playlists 里按标题找到本月片单 ID，
    再按普通榜单取条目。月初当月片单还没发布时退回列表里出现的第一个月度片单
    （列表不是严格按发布时间排，月初上一期是否还在第一页未验证，找不到时直接报错）。"""
    payload = await _fetch_json(
        f"{REXXAR}/skynet/new_playlists",
        meta,
        referer="https://m.douban.com/movie/",
        params={"subject_type": subject_type},
        no_cache=no_cache,
    )
    blocks = payload.get("data") or []
    if not isinstance(blocks, list):
        raise RuntimeError("douban skynet/new_playlists response data is not a list")  # noqa: TRY004
    playlists = [
        item
        for block in blocks
        if isinstance(block, dict)
        for item in (block.get("items") or [])
        if isinstance(item, dict)
    ]
    now = datetime.now(CHINA_TZ)
    word = "新剧" if subject_type == "tv" else "电影"
    pattern = re.compile(rf"^\d{{4}}年\d{{2}}月.*热门{word}推荐")
    monthly = [it for it in playlists if pattern.search(str(it.get("title") or ""))]
    current = [
        it
        for it in monthly
        if str(it.get("title")).startswith(f"{now.year}年{now.month:02d}月")
    ]
    chosen = (current or monthly or [None])[0]
    if not chosen or not chosen.get("id"):
        raise RuntimeError(
            f"douban skynet/new_playlists has no 'YYYY年MM月…热门{word}推荐' playlist "
            f"({len(playlists)} playlists)"
        )
    items, _, link = await _fetch_collection(str(chosen["id"]), no_cache, meta)
    return items, str(chosen.get("title")), link


async def _fetch_box_office(
    no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    page = await _fetch_text("https://movie.douban.com/chart", meta, no_cache=no_cache)
    start = page.find("<h2>北美票房榜")
    section = page[start : page.find("</ul>", start)] if start >= 0 else ""
    head = re.search(r'<span class="box_chart_num color-gray">([^<]*)</span></h2>', section)
    items: list[ListItem] = []
    for li in re.findall(r'<li class="clearfix">(.*?)</li>', section, re.DOTALL):
        match = re.search(r'href="https://movie\.douban\.com/subject/(\d+)/">(.*?)</a>', li, re.DOTALL)
        box = re.search(r'<span class="box_chart_num color-gray">([^<]*)</span>', li)
        if not match:
            continue
        sid, title = match.group(1), _text(match.group(2))
        gross = box.group(1).strip() if box else ""
        items.append(
            ListItem(
                id=sid,
                title=title,
                url=f"https://movie.douban.com/subject/{sid}/",
                mobileUrl=f"https://m.douban.com/movie/subject/{sid}/",
                hot=_number(gross),
                desc=_join(gross and f"票房 {gross}美元", "新上榜" if "box_new" in li else None),
            )
        )
    note = f"北美票房榜 {head.group(1).strip()}" if head else None
    return items, note, "https://movie.douban.com/chart"


async def _fetch_later(no_cache: bool, meta: _FetchMeta) -> tuple[list[ListItem], str | None, str]:
    page = await _fetch_text(
        f"https://movie.douban.com/cinema/later/{CITY}/", meta, no_cache=no_cache
    )
    section = page[page.find('id="showing-soon"') :]
    items: list[ListItem] = []
    for block in re.split(r'<div class="item mod[^"]*">', section)[1:]:
        match = re.search(
            r'<h3>\s*<a href="https://movie\.douban\.com/subject/(\d+)/"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        if not match:
            continue
        sid, title = match.group(1), _text(match.group(2))
        dts = [_text(x) for x in re.findall(r'<li class="dt[^"]*">(.*?)</li>', block, re.DOTALL)]
        img = re.search(r'<img src="([^"]+)"', block)
        wish = next((x for x in dts if "想看" in x), "")
        info = [x for x in dts if x and x != wish]
        items.append(
            ListItem(
                id=sid,
                title=title,
                url=f"https://movie.douban.com/subject/{sid}/",
                mobileUrl=f"https://m.douban.com/movie/subject/{sid}/",
                hot=_number(wish),
                cover=img.group(1) if img else None,
                desc=_join(info[0] + " 上映" if info else None, *info[1:], wish),
            )
        )
    return items, f"城市：{CITY}", f"https://movie.douban.com/cinema/later/{CITY}/"


async def _fetch_nowplaying(
    min_score: float, no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    page = await _fetch_text(
        f"https://movie.douban.com/cinema/nowplaying/{CITY}/", meta, no_cache=no_cache
    )
    start = page.find('<div id="nowplaying">')
    end = page.find('<div id="upcoming">', start)
    section = page[start : end if end > 0 else None] if start >= 0 else ""
    items: list[ListItem] = []
    for match in re.finditer(r'<li\s+id="(\d+)"\s+class="list-item[^"]*"(.*?)>', section, re.DOTALL):
        attrs = {
            key: html.unescape(value)
            for key, value in re.findall(r'data-(\w+)="([^"]*)"', match.group(2))
        }
        if attrs.get("category") != "nowplaying":
            continue
        try:
            score = float(attrs.get("score") or 0)
        except ValueError:
            score = 0.0
        if min_score and score < min_score:
            continue
        sid = match.group(1)
        img = re.search(r"<img src=\"([^\"]+)\"", section[match.end() : match.end() + 1500])
        items.append(
            ListItem(
                id=sid,
                title=attrs.get("title") or sid,
                url=f"https://movie.douban.com/subject/{sid}/",
                mobileUrl=f"https://m.douban.com/movie/subject/{sid}/",
                hot=attrs.get("votecount") or None,
                cover=img.group(1) if img else None,
                desc=_join(
                    f"评分 {score:.1f}" if score else "暂无评分",
                    attrs.get("release"),
                    attrs.get("duration"),
                    attrs.get("region"),
                    attrs.get("director") and f"导演 {attrs['director']}",
                    attrs.get("actors") and f"主演 {attrs['actors']}",
                ),
            )
        )
    note = f"城市：{CITY}" + (f"；评分 >= {min_score}" if min_score else "")
    return items, note, f"https://movie.douban.com/cinema/nowplaying/{CITY}/"


async def _fetch_recent_hot(
    tab: str, no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    """原站"选剧集"页的"最近热门剧集"列表（旧版 /j/search_subjects 现行页面已不再调用）。
    热门美剧：现行页面没有"美剧"页签，对应"欧美剧"（type=tv_american，与榜单 tv_american 是同一份列表）。"""
    payload = await _fetch_json(
        f"{REXXAR}/subject/recent_hot/tv",
        meta,
        referer="https://movie.douban.com/tv/",
        params={"type": tab, "start": 0, "limit": RECENT_HOT_PAGE},
        no_cache=no_cache,
    )
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("douban recent_hot/tv response items is not a list")  # noqa: TRY004
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "")
        title = str(row.get("title") or "").strip()
        if not sid or not title:
            continue
        rating = row.get("rating") if isinstance(row.get("rating"), dict) else {}
        value = rating.get("value")
        pic = row.get("pic") if isinstance(row.get("pic"), dict) else {}
        items.append(
            ListItem(
                id=sid,
                title=title,
                url=f"https://movie.douban.com/subject/{sid}/",
                mobileUrl=f"https://m.douban.com/movie/subject/{sid}/",
                cover=pic.get("large") or pic.get("normal"),
                # is_new 是该分支唯一的原生标识
                badges=[{"text": "新上线"}] if row.get("is_new") is True else [],
                desc=_join(
                    value and f"评分 {value}",
                    row.get("episodes_info"),
                    row.get("card_subtitle"),
                    "新上线" if row.get("is_new") else None,
                ),
            )
        )
    note = f"最近热门剧集 · {RECENT_HOT_TABS.get(tab, tab)}"
    return items, note, "https://movie.douban.com/tv/"


async def _fetch_hot_search(
    no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    # 接口固定返回 15 条，count / start 参数不起作用（board_api verify/probe_log）；
    # 响应是顶层数组而非对象，单独走 _fetch 校验
    result = await _fetch(
        f"{REXXAR}/chart/hot_search_board",
        referer="https://www.douban.com/gallery/",
        params={"count": 15, "start": 0},
        no_cache=no_cache,
    )
    meta.observe(result)
    rows = result.data if isinstance(result.data, list) else []
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            items.append(
                ListItem(
                    id=name,
                    title=name,
                    url="https://www.douban.com/search?q=" + quote(f"#{name}#"),
                    hot=row.get("score"),
                )
            )
    return items, None, "https://www.douban.com/gallery/"


async def _fetch_web_hot_topics(
    no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    # 页面每次展示 6 个（"换一批"），接口一次最多给 50 个（total=50，count=100 也只有 50）；
    # 页不满（实测出现过一次）时重取一次
    url = f"{REXXAR}/gallery/web_hot_topics"
    referer = "https://www.douban.com/gallery/"
    params: dict[str, Any] = {"count": 50, "start": 0}
    payload = await _fetch_json(url, meta, referer=referer, params=params, no_cache=no_cache)
    topics = payload.get("items")
    if not isinstance(topics, list):
        raise RuntimeError("douban web_hot_topics response items is not a list")  # noqa: TRY004
    if not topics or len(topics) < min(50, _as_int(payload.get("total"))):
        retry = await _fetch_json(url, meta, referer=referer, params=params, no_cache=no_cache)
        topics = retry.get("items") or []
    items: list[ListItem] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        tid = str(topic.get("id") or "")
        name = str(topic.get("name") or topic.get("title") or "").strip()
        if tid and name:
            items.append(
                ListItem(
                    id=tid,
                    title=name,
                    url=f"https://www.douban.com/gallery/topic/{tid}/",
                    mobileUrl=f"https://m.douban.com/gallery/topic/{tid}/",
                    hot=topic.get("read_count"),
                    desc=topic.get("card_subtitle"),
                )
            )
    return items, None, "https://www.douban.com/gallery/"


async def _fetch_gallery_all(
    no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    page = await _fetch_text("https://www.douban.com/gallery/all", meta, no_cache=no_cache)
    items: list[ListItem] = []
    for li in re.findall(r'<li class="topic-link"[^>]*>(.*?)</li>', page, re.DOTALL):
        match = re.search(
            r'href="https://www\.douban\.com/gallery/topic/(\d+)/"[^>]*>(.*?)</a>', li, re.DOTALL
        )
        if not match:
            continue
        tid, title = match.group(1), _text(match.group(2))
        views = re.search(r'<span class="count">([^<]*)</span>', li)
        views_text = views.group(1).strip() if views else ""
        items.append(
            ListItem(
                id=tid,
                title=title,
                url=f"https://www.douban.com/gallery/topic/{tid}/",
                mobileUrl=f"https://m.douban.com/gallery/topic/{tid}/",
                hot=_number(views_text) if views_text else None,
                desc=_join("活动" if "activity-label" in li else None, views_text),
            )
        )
    note = "全部话题第一页（页面其余部分靠“显示更多”按钮加载）"
    return items, note, "https://www.douban.com/gallery/all"


def _draft_text(desc: str) -> str:
    """影评摘要是截断的 Draft.js JSON，取其中各段 text 拼起来。"""
    texts = []
    # 最后一段通常被截断（以 ... 结尾、没有结尾引号），也要取；截断处可能留下半个 \uXXXX 转义，先去掉
    for raw in re.findall(r'"text":\s*"((?:[^"\\]|\\.)*)', desc):
        raw = re.sub(r"\\(u[0-9a-fA-F]{0,3})?$", "", re.sub(r"(\.\.\.|…)$", "", raw))
        try:
            texts.append(json.loads(f'"{raw}"'))
        except ValueError:
            continue
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


async def _fetch_review_feed(
    no_cache: bool, meta: _FetchMeta
) -> tuple[list[ListItem], str | None, str]:
    """豆瓣官方 RSS，约 20 条 = 原站 /review/best/ 第 1 页，同顺序。
    保持原站顺序（"最受欢迎"的名次；tophub 把这 20 条按发布时间倒序显示，不照它重排）。"""
    xml = await _fetch_text("https://www.douban.com/feed/review/movie", meta, no_cache=no_cache)
    items: list[ListItem] = []
    for node in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):

        def tag(name: str, node: str = node) -> str:
            found = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", node, re.DOTALL)
            return found.group(1).strip() if found else ""

        link, title = tag("link"), _text(tag("title"))
        rid = re.search(r"/review/(\d+)/", link)
        if not rid or not title:
            continue
        desc = html.unescape(tag("description"))
        head = re.sub(r"\s*\(https?://[^)]*\)", "", desc.split("{", 1)[0])
        head = re.sub(r"\s+", " ", head).strip()
        cover = re.search(r'<img src="([^"]+)"', tag("content:encoded"))
        try:
            timestamp = get_time(parsedate_to_datetime(tag("pubDate")).timestamp())
        except (TypeError, ValueError, IndexError):
            timestamp = None
        items.append(
            ListItem(
                id=rid.group(1),
                title=title,
                url=link,
                mobileUrl=f"https://m.douban.com/movie/review/{rid.group(1)}/",
                author=_text(tag("dc:creator")) or None,
                cover=cover.group(1) if cover else None,
                desc=_join(head, _draft_text(desc)),
                timestamp=timestamp,
            )
        )
    return items, None, "https://movie.douban.com/review/best/"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, kind, arg = _BOARDS[type_param]
    meta = _FetchMeta()
    if kind == "collection":
        items, note, link = await _fetch_collection(arg, no_cache, meta)
    elif kind == "monthly":
        items, note, link = await _fetch_monthly(arg, no_cache, meta)
    elif kind == "box_office":
        items, note, link = await _fetch_box_office(no_cache, meta)
    elif kind == "later":
        items, note, link = await _fetch_later(no_cache, meta)
    elif kind == "nowplaying":
        items, note, link = await _fetch_nowplaying(float(arg or 0), no_cache, meta)
    elif kind == "recent_hot":
        items, note, link = await _fetch_recent_hot(arg, no_cache, meta)
    elif kind == "hot_search":
        items, note, link = await _fetch_hot_search(no_cache, meta)
    elif kind == "web_hot_topics":
        items, note, link = await _fetch_web_hot_topics(no_cache, meta)
    elif kind == "gallery_all":
        items, note, link = await _fetch_gallery_all(no_cache, meta)
    else:
        items, note, link = await _fetch_review_feed(no_cache, meta)
    unique: dict[str, ListItem] = {}
    for item in items:  # 按 id 去重，保留首次出现的名次
        unique.setdefault(item.id, item)
    items = list(unique.values())[:MAX_ITEMS]
    if not items:
        # 错误页 / 登录跳转 / 改版空解析都不允许静默降级为空榜
        raise RuntimeError(f"douban {label} ({type_param}) parsed no items; feed may have changed")
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=label,
        total=len(items),
        fromCache=meta.from_cache,
        updateTime=meta.update_time,
        data=items,
        message=note,
    )
