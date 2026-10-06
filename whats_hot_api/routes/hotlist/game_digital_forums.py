from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "game-digital-forums"

type_map: dict[str, str] = {
    "s1-anime": "Stage1st · 动漫论坛（最新发表）",
    "s1-game": "Stage1st · 游戏论坛（最新发表）",
    "s1-latest": "Stage1st · 最新（全站最新 20 帖）",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "游戏与数码论坛",
    "description": "Stage1st 动漫论坛、游戏论坛（按发帖时间）与全站最新。",
    "link": "https://stage1st.com/2b/",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}

BEIJING = timezone(timedelta(hours=8))
S1 = "https://stage1st.com/2b/"
S1_FORUMS = {"s1-anime": 6, "s1-game": 4}
S1_RSS = S1 + "forum.php?mod=rss"  # 不带 fid:全站最新 20 帖


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _int(value: str) -> int | None:
    m = re.search(r"[\d,]+", (value or "").replace(" ", ""))
    return int(m.group().replace(",", "")) if m else None


def _discuz_ts(value: str) -> int | None:
    """Discuz 的"2026-9-28 07:50"(北京时间)-> 毫秒。"""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(value, fmt).replace(tzinfo=BEIJING).timestamp()) * 1000
        except ValueError:
            continue
    return None


def _discuz_time(em: Tag | None) -> int | None:
    """发帖时间:一般是"2026-9-28 07:50";较新的帖子显示"3 小时前",完整时间在 span 的 title 里。"""
    if em is None:
        return None
    span = em.select_one("span[title]")
    if span is not None:
        ts = _discuz_ts(str(span.get("title") or ""))
        if ts:
            return ts
    return _discuz_ts(_text(em))


def _parse_discuz_threads(html: str, base: str) -> list[ListItem]:
    """Discuz 缺省模板主题列表:先置顶(stickthread_),再普通(normalthread_),与页面顺序一致。
    版块页第一个 td.by 是作者+时间。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for tbody in soup.select("tbody[id^=stickthread_], tbody[id^=normalthread_]"):
        tid = str(tbody.get("id") or "").split("_", 1)[-1]
        a = tbody.select_one("a.xst")
        if not tid.isdigit() or a is None or tid in seen:
            continue
        title = _text(a)
        if not title:
            continue
        seen.add(tid)
        by = tbody.select_one("td.by")
        num = tbody.select_one("td.num em")  # 查看数
        sticky = str(tbody.get("id")).startswith("stick")
        url = f"{base}thread-{tid}-1-1.html"
        items.append(ListItem(id=tid, title=title, url=url, mobileUrl=url,
                              hot=_int(_text(num)) if num else None,
                              author=(_text(by.select_one("cite")) or None) if by else None,
                              desc="置顶" if sticky else None,
                              timestamp=_discuz_time(by.select_one("em")) if by else None))
    return items


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "s1-anime")
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _get_list(board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board: str, no_cache: bool) -> dict:
    if board in S1_FORUMS:
        result = await get(
            url=f"{S1}forum.php?mod=forumdisplay&fid={S1_FORUMS[board]}&filter=author&orderby=dateline",
            no_cache=no_cache, response_type="text",
        )
        items = _parse_discuz_threads(str(result.data), S1)
    else:  # s1-latest
        result = await get(
            url=S1_RSS,
            headers={"Accept": "application/rss+xml,application/xml,text/xml,*/*"},
            no_cache=no_cache, response_type="text",
        )
        text = str(result.data)
        if "<rss" not in text[:500]:
            raise RuntimeError(f"Stage1st site RSS did not return RSS ({result.data!r:.120})")
        out: list[ListItem] = []
        for it in parse_feed(text):  # 保留 feed 原顺序
            m = re.search(r"thread-(\d+)-|[?&]tid=(\d+)", it.url)
            out.append(it.model_copy(update={"id": (m.group(1) or m.group(2)) if m else it.id}))
        items = out
        if not items:
            # Discuz 的 RSS 缓存重建时会短暂返回 0 条
            raise RuntimeError("Stage1st site RSS returned 0 items this run (Discuz RSS cache rebuild), retry later")
    if not items:
        raise RuntimeError(f"game-forums board '{board}' parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}
