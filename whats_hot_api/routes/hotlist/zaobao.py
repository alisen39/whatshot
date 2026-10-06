"""联合早报栏目(www.zaobao.com 服务端渲染的 Astro 页面,公开、无签名、无 cookie)。

board_api 单元 `tmp/board_api/zaobao_channels` 的 1:1 迁移(EXTEND+REPAIR),证据见该目录
README 与 `analysis_report.md`、`verify/whatshot_rule_check.txt`、`verify/timestamp_check.log`。

修复点:文章链接已从 `/realtime/…` 改为 `/news/<栏目>/story…`,旧规则(链接文字 ≥6 字且
href 含 `/realtime/`)命中 0 条;现按页面卡片取数,不再看链接前缀。同时补上 10 个栏目的
type 表(声明序第一个 realtime-china 即时中国是默认榜,与旧路由同一页面 /realtime/china,
行为保持不变,只是解析修好了)。

- 即时中国/国际/新加坡:`/realtime/{china,world,singapore}`,27 条 = 18 张静态卡片 +
  LoadMoreList 岛里服务端渲染的 9 张(第一屏);新闻中国/国际/新加坡:`/news/*` 27 条,
  与 /realtime/* 是同一份列表(带配图),按 board_api 口径各取各的页面、分开算
- 中国财经/全球财经/财经即时:`/finance/{china,world,singapore}` 18 条("财经即时"的
  tophub 条目全是 /finance/singapore 稿);下午察:关键词页 `/keywords/xia-wu-cha` 18 条
- 列表 = `<main>` 里的 `<article>` 卡片(a.article-link,title 属性是完整标题);侧栏
  "热门"是 HotNews 岛(20 条全站热门), decompose 掉再取卡片
- 发布时间(新加坡时间 UTC+8,页面脚本按 publicationDate 与渲染时刻格式化):
  不到 1 分钟"刚刚"、不到 1 小时"N分钟前"、当天"HH:MM"、更早"[YYYY年]M月D日";
  即时页 LoadMoreList 岛 props 的 publicationDate 精确到秒,直接用;"刚刚 / N分钟前"
  页面经多层缓存推不准渲染时刻(实测偏差 0~229 秒),逐条取详情页 JSON-LD 的
  datePublished(每条多 1 个请求,通常每页 0~几条),取不到才退回按渲染时刻的估计值并
  写 message;"HH:MM"取渲染当天该时刻(估计跨过午夜时退回前一天);"M月D日"只显示到日,
  取该日 0 点。渲染时刻用本路由收到响应的时刻估计(Core 的共享 HTTP 缓存不透出 Age
  响应头,拿不到 CDN 记的渲染时刻;误差与 board_api 的 Age 倒推同量级,分钟级)
- 卡片时间位是卡片里最后一个 <span>(前面可能有栏目名、"·");整段符合上面几种写法才认,
  标题里的"9月18日"不算。链接 story 后的日期有时是更新日期,不当发布时间用
- id 是卡片链接的站内路径(如 /news/china/story20260927-9745158,与旧路由写法相同);
  desc/author/hot 卡片不提供;cover 只有 /news/*、/finance/*、/keywords/* 卡片带
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zaobao"

WWW = "https://www.zaobao.com/"

# 子榜键 -> (中文名, 栏目路径)。声明序第一个(realtime-china,即时中国)是默认榜,
# 与旧路由同一个页面 /realtime/china。
_BOARDS: dict[str, tuple[str, str]] = {
    "realtime-china": ("即时中国", "realtime/china"),
    "realtime-world": ("即时国际", "realtime/world"),
    "realtime-singapore": ("即时新加坡", "realtime/singapore"),
    "news-china": ("新闻中国", "news/china"),
    "news-world": ("新闻国际", "news/world"),
    "news-singapore": ("新闻新加坡", "news/singapore"),
    "finance-china": ("中国财经", "finance/china"),
    "finance-world": ("全球财经", "finance/world"),
    "finance-singapore": ("财经即时（新加坡财经）", "finance/singapore"),
    "xia-wu-cha": ("下午察", "keywords/xia-wu-cha"),
}

type_map: dict[str, str] = {key: board[0] for key, board in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "联合早报",
    "description": (
        "联合早报网栏目:即时/新闻的中国、国际、新加坡,中国财经、全球财经、"
        "财经即时(新加坡财经),下午察。"
    ),
    "link": WWW,
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_DEFAULT_TYPE = next(iter(type_map))
_SGT = timezone(timedelta(hours=8))
# 卡片时间位的几种写法(页面格式化函数 index.*.js 的输出;"N小时前"页面不会产生,仍兼容)
_SHOWN_DATE = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日")
_SHOWN_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")
_SHOWN_AGO = re.compile(r"(\d+)\s*(分钟|小时)前")
# 详情页 JSON-LD:"2026-09-28T07:02:34+08:00"
_DATE_PUBLISHED = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')

# header_check 实测浏览器 UA / curl UA / 无 UA / python-httpx UA 都返回 200 且字节数相同,
# 请求头非必需;旧路由就带 UA,这里保持带浏览器 UA 的口径
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}


def _now_sgt() -> datetime:
    """页面渲染时刻的估计(新加坡时间)。页面过 Varnish 与阿里云 CDN 多层缓存,board_api
    按 Age 响应头倒推实测偏差 0~229 秒;Core 的共享 HTTP 缓存不透出响应头,这里直接用
    收到响应的时刻,误差同量级(分钟级),只影响"N分钟前"的兜底估计与"HH:MM"的日期。"""
    return datetime.now(tz=_SGT)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _shown_seconds(text: str, now: datetime) -> int | None:
    """卡片时间位文字 -> Unix 秒(get_time 再统一转毫秒);认不出的返回 None。"""
    if text == "刚刚":
        return int(now.timestamp())
    if match := _SHOWN_AGO.fullmatch(text):
        delta = (
            timedelta(minutes=int(match.group(1)))
            if match.group(2) == "分钟"
            else timedelta(hours=int(match.group(1)))
        )
        return int((now - delta).timestamp())
    try:
        if match := _SHOWN_CLOCK.fullmatch(text):
            moment = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
            # "HH:MM"只给渲染当天、至少 1 小时前的稿;估计的渲染时刻比实际晚,跨过午夜时
            # 会落到第二天,退回前一天
            if moment > now:
                moment -= timedelta(days=1)
            return int(moment.timestamp())
        if match := _SHOWN_DATE.fullmatch(text):
            year = int(match.group(1)) if match.group(1) else now.year  # 格式化函数只在跨年时带年份
            return int(datetime(year, int(match.group(2)), int(match.group(3)), tzinfo=_SGT).timestamp())
    except ValueError:
        return None
    return None


def _card_seconds(card: Tag, now: datetime) -> tuple[int | None, bool]:
    """卡片底部的时间位是卡片里最后一个 <span>;只认整段符合几种写法的。
    返回 (Unix 秒, 是否相对时间);相对时间(刚刚 / N分钟前)按渲染时刻估计,
    调用方再用详情页时间替换。"""
    for span in reversed(card.select("span")):
        text = span.get_text(strip=True)
        seconds = _shown_seconds(text, now)
        if seconds is not None:
            return seconds, text == "刚刚" or bool(_SHOWN_AGO.fullmatch(text))
    return None, False


def _astro_value(value: Any) -> Any:
    """Astro 岛 props 的序列化:[0, 值] 是普通值、[1, [...]] 是数组,逐层解开。"""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        kind, inner = value
        if kind == 0:
            return {k: _astro_value(v) for k, v in inner.items()} if isinstance(inner, dict) else inner
        if kind == 1 and isinstance(inner, list):
            return [_astro_value(item) for item in inner]
        return inner
    return value


def _island_seconds(main: Tag) -> dict[str, int]:
    """即时页 LoadMoreList 岛(服务端已渲染成卡片的 9 条)props 里的 publicationDate
    ("2026-09-27 13:26:00",新加坡时间,精确到秒)。站内路径 -> Unix 毫秒。"""
    seconds_map: dict[str, int] = {}
    for island in main.select("astro-island[props]"):
        try:
            props = json.loads(str(island.get("props") or ""))
        except ValueError:
            continue
        rows = _astro_value(props.get("list")) if isinstance(props, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                moment = datetime.strptime(str(row.get("publicationDate") or ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SGT)
            except ValueError:
                continue
            path = str(row.get("url") or "").split("?")[0]
            milliseconds = get_time(int(moment.timestamp()))
            if path and milliseconds is not None:
                seconds_map[path] = milliseconds
    return seconds_map


def _parse_list(html: str, now: datetime) -> tuple[list[ListItem], set[str]]:
    """解析栏目页:<main> 里的 <article> 卡片(先去掉侧栏"热门"HotNews 岛)。
    返回 (条目, 时间来自相对时间估计的条目 id)。"""
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("main")
    if not isinstance(main, Tag):
        raise RuntimeError("zaobao page has no <main> (page structure changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    # 侧栏"热门"是 HotNews 岛(20 条全站热门),不是本栏目列表
    for island in main.select("astro-island"):
        if "HotNews" in str(island.get("component-url") or ""):
            island.decompose()
    exact = _island_seconds(main)
    items: list[ListItem] = []
    relative: set[str] = set()
    seen: set[str] = set()
    for card in main.select("article"):
        anchor = card.select_one("a.article-link[href*='/story']") or card.select_one("a[href*='/story']")
        if not isinstance(anchor, Tag):
            continue
        href = str(anchor.get("href") or "").strip()
        path = href.split("?")[0]
        url = urljoin(WWW, href)
        title = _clean_text(str(anchor.get("title") or "") or anchor.get_text(" ", strip=True))
        if not title or url in seen:
            continue
        seen.add(url)
        img = card.select_one("img[src]")
        cover = str(img.get("src") or "").strip() if isinstance(img, Tag) else ""
        if path in exact:
            timestamp, is_relative = exact[path], False
        else:
            seconds, is_relative = _card_seconds(card, now)
            timestamp = get_time(seconds) if seconds is not None else None
        if is_relative:
            relative.add(path)
        items.append(
            ListItem(
                id=path,
                title=title,
                url=url,
                mobileUrl=url,
                cover=cover if cover.startswith(("http://", "https://")) else None,
                timestamp=timestamp,
            )
        )
    return items, relative


def _detail_timestamp(html: str) -> int | None:
    """详情页 JSON-LD 的 datePublished -> Unix 毫秒。"""
    match = _DATE_PUBLISHED.search(html)
    if not match:
        return None
    try:
        return get_time(int(datetime.fromisoformat(match.group(1)).timestamp()))
    except ValueError:
        return None


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", _DEFAULT_TYPE)
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    label, section = _BOARDS[board_type]
    url = f"{WWW}{section}"

    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text")
    html = result.data if isinstance(result.data, str) else ""
    items, relative = _parse_list(html, _now_sgt())
    if not items:
        # 错误页 / 业务错误壳 / 空解析不静默降级为空榜
        raise RuntimeError(f"zaobao board '{board_type}' parsed no items: {url}")

    # "刚刚 / N分钟前"的卡片逐条取详情页发布时间;取不到的保留按渲染时刻的估计值
    fixed: dict[str, int] = {}
    for item in items:
        if item.id not in relative:
            continue
        try:
            detail = await get(url=item.url, headers=_HEADERS, no_cache=no_cache, response_type="text")
            timestamp = _detail_timestamp(detail.data) if isinstance(detail.data, str) else None
        except Exception:  # noqa: BLE001 - 详情页失败只是退回估计值(证据口径)
            timestamp = None
        if timestamp is not None:
            fixed[item.id] = timestamp
    message: str | None = None
    if missing := len(relative - fixed.keys()):
        message = (
            f"{missing} 条「N分钟前」的稿没有取到详情页发布时间,"
            "timestamp 按页面渲染时刻估计(误差可达 4 分钟)"
        )
    if fixed:
        # 用详情页时间替换估计值(model_copy 会再过一遍校验器,保持毫秒口径)
        items = [item.model_copy(update={"timestamp": fixed[item.id]}) if item.id in fixed else item for item in items]

    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
        message=message,
    )
