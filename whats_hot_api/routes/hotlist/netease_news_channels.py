from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "netease-news-channels"

type_map: dict[str, str] = {
    "touch-news": "今日关注（手机网易网要闻）",
    "touch-jiankang": "健康频道",
    "exclusive-qsyk": "轻松一刻",
    "exclusive-cz": "槽值",
    "exclusive-lc": "浪潮",
    "exclusive-kk": "看客",
    "exclusive-txs": "谈心社",
    "news-latest": "滚动新闻",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "网易新闻",
    "description": "网易新闻栏目：手机网易网要闻（今日关注）、健康频道、网易专栏（轻松一刻、槽值、浪潮、看客、谈心社）、滚动新闻",
    "link": "https://m.163.com/touch/news/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

M_HOST = "https://m.163.com"
# 子榜 -> (页面, 信息流 topicId, 频道路径);首屏数据整份在页面 __INITIAL_STATE__ 里
TOUCH_PAGES: dict[str, tuple[str, str, str]] = {
    "touch-news": (f"{M_HOST}/touch/news/", "BBM54PGAwangning", "news"),
    "touch-jiankang": (f"{M_HOST}/touch/jiankang/", "BDC4QSV3wangning", "jiankang"),
    "exclusive-qsyk": (f"{M_HOST}/touch/exclusive/sub/qsyk", "BD21K0DLwangning", "exclusive"),
    "exclusive-cz": (f"{M_HOST}/touch/exclusive/sub/cz", "CICMICLUwangning", "exclusive"),
    "exclusive-lc": (f"{M_HOST}/touch/exclusive/sub/lc", "CICMMGBHwangning", "exclusive"),
    "exclusive-kk": (f"{M_HOST}/touch/exclusive/sub/kk", "D55253RHwangning", "exclusive"),
    "exclusive-txs": (f"{M_HOST}/touch/exclusive/sub/txs", "D553PGHQwangning", "exclusive"),
}
HOME_FOCUS_TOPIC = "BCR0CBQ2wangning"  # 要闻页焦点图
LATEST_PAGE = "https://news.163.com/latest/"
LATEST_DATA = "https://news.163.com/special/0001220O/new_json2021.js"
LATEST_PAGE_SIZE = 40  # instantNews.5.js:t.size = cookie 里的条数 || 40
BEIJING = timezone(timedelta(hours=8))
DOCID_RE = re.compile(r"/([0-9A-Z]{16})\.html")
ARTICLE_DOCID_RE = re.compile(r"[0-9A-Z]{16}")


def _timestamp(value: Any) -> int | None:
    """北京时间 "YYYY-MM-DD HH:MM:SS" -> 毫秒。"""
    try:
        dt = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING)
    except ValueError:
        return None
    return int(dt.timestamp()) * 1000


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _initial_state(html: str, page: str) -> dict[str, Any]:
    marker = "window.__INITIAL_STATE__="
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"netease page has no __INITIAL_STATE__: {page}")
    state, _ = json.JSONDecoder().raw_decode(html, start + len(marker))
    store = state.get("store") if isinstance(state, dict) else None
    if not isinstance(store, dict):
        raise RuntimeError(f"netease page __INITIAL_STATE__ has no store: {page}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    return store


def _topic_list(store: dict[str, Any], topic_id: str) -> list[dict[str, Any]]:
    """按 params.topicId 找列表(store 键名随栏目变化,如 qsykArticleList、homeArticleList)。"""
    for value in store.values():
        if isinstance(value, dict) and isinstance(value.get("params"), dict) and value["params"].get("topicId") == topic_id:
            rows = (value.get("data") or {}).get("list")
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    raise RuntimeError(f"netease page state has no list for topicId={topic_id}")


def _visible(row: dict[str, Any]) -> bool:
    """前端过滤:来源+摘要含 # 只对北京以外显示,含 $ 只对北京显示,否则隐藏"网易彩票"。按非北京访客处理。"""
    text = f"{row.get('source') or ''}{row.get('digest') or ''}"
    if "#" in text:
        return True
    if "$" in text:
        return False
    return "网易彩票" not in text


def _flow_link(row: dict[str, Any], channel: str) -> str | None:
    """照前端 Oa() 拼卡片链接(相对 m.163.com);非文章占位记录(商业合作)不算条目。"""
    docid = str(row.get("docid") or "").strip()
    skip = row.get("skipType") or ""
    stitle = str(row.get("stitle") or "")
    if skip == "video":
        return f"{M_HOST}/{channel}/video/{docid}.html" if docid else None
    if skip == "special" and row.get("specialID"):
        return f"{M_HOST}/{channel}/special/{row['specialID']}.html"
    if skip == "photoset" and row.get("photosetID"):
        parts = str(row["photosetID"]).split("|")
        return f"{M_HOST}/{channel}/photoview/{parts[0]}/{parts[1]}.html" if len(parts) >= 2 else None
    if skip == "live" and docid:
        return f"{M_HOST}/touch/live.html?roomid={docid}"
    if skip == "paidCollect" and docid:
        return f"{M_HOST}/dy/paidCollect/{docid}.html"
    head, _, tail = stitle.partition("|")
    if head == "WEB" and tail.startswith(("http://", "https://")):
        return tail
    return f"{M_HOST}/{channel}/article/{docid}.html" if ARTICLE_DOCID_RE.fullmatch(docid) else None


def _flow_item(row: dict[str, Any], channel: str) -> ListItem | None:
    title = _text(row.get("title"))
    link = _flow_link(row, channel)
    if not title or not link:
        return None
    return ListItem(
        id=str(row.get("docid") or link),
        title=title,
        url=link,
        mobileUrl=link,
        hot=row.get("commentCount"),
        cover=row.get("imgsrc") or None,
        author=_text(row.get("source")) or None,
        desc=_text(row.get("digest")) or None,
        timestamp=_timestamp(row.get("ptime")),
    )


def _top_news_link(row: dict[str, Any]) -> str | None:
    """照要闻页 TopNews 组件拼链接;不认识的类型前端不显示。"""
    kind, typeid, docid = row.get("type"), str(row.get("typeid") or ""), str(row.get("docid") or "")
    channel = row.get("channel") or "news"
    if kind == "special" and typeid:
        return f"{M_HOST}/{channel}/special/{typeid.split('#')[0]}.html"
    if kind == "photoset" and "|" in typeid:
        first, second = typeid.split("|")[:2]
        return f"{M_HOST}/{channel}/photoview/{first[-4:]}/{second}.html"
    if kind == "live" and typeid:
        return f"{M_HOST}/touch/live.html?roomid={typeid}"
    if kind == "video" and typeid:
        return f"{M_HOST}/{channel}/video/{typeid}.html"
    if kind == "doc" and ARTICLE_DOCID_RE.fullmatch(docid):
        return f"{M_HOST}/{channel}/article/{docid}.html"
    return None


def _top_news_item(row: dict[str, Any]) -> ListItem | None:
    title = _text(row.get("title"))
    link = _top_news_link(row)
    if not title or not link:
        return None
    pics = row.get("picInfo") or []
    cover = pics[0].get("url") if pics and isinstance(pics[0], dict) else None
    return ListItem(
        id=str(row.get("docid") or link),
        title=title,
        url=link,
        mobileUrl=link,
        hot=row.get("tcount"),
        cover=cover,
        author=_text(row.get("source")) or None,
        desc=_text(row.get("digest")) or None,
        timestamp=_timestamp(row.get("ptime")),
    )


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """前端 uniqueArticleList:按 docid 去重,保留第一次。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        docid = str(row.get("docid") or "")
        if docid and docid in seen:
            continue
        seen.add(docid)
        out.append(row)
    return out


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "touch-news")
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _get_list(board, no_cache)
    return RouterData(
        **ROUTE_META,
        type="滚动新闻（最新）" if board == "news-latest" else type_map[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board: str, no_cache: bool) -> dict:
    if board == "news-latest":
        return await _fetch_latest(no_cache)
    return await _fetch_touch(board, no_cache)


async def _fetch_touch(board: str, no_cache: bool) -> dict:
    page, topic_id, channel = TOUCH_PAGES[board]
    result = await get(url=page, no_cache=no_cache, response_type="text")
    store = _initial_state(str(result.data), page)
    blocks: list[ListItem | None] = []
    if board == "touch-news":
        # 焦点图(同样经过去重和过滤)→ 置顶要闻 → 信息流
        blocks += [_flow_item(row, channel) for row in _dedupe(_topic_list(store, HOME_FOCUS_TOPIC)) if _visible(row)]
        important = store.get("importantNews") or {}
        toutiao = ((important.get("data") or {}).get("toutiao")) or []
        blocks += [_top_news_item(row) for row in toutiao if isinstance(row, dict) and row.get("isTop")]
    blocks += [_flow_item(row, channel) for row in _dedupe(_topic_list(store, topic_id)) if _visible(row)]
    items: list[ListItem] = []
    seen: set[str] = set()
    for item in blocks:
        if item is None or item.id in seen:
            continue
        seen.add(item.id)
        items.append(item)
    if not items:
        raise RuntimeError(f"netease board '{board}' parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _fetch_latest(no_cache: bool) -> dict:
    result = await get(
        url=LATEST_DATA,
        headers={"Referer": LATEST_PAGE},
        no_cache=no_cache,
        response_type="text",
    )
    text = str(result.data)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"netease latest data file has unexpected format: {LATEST_DATA}")
    data = json.loads(text[start:end + 1])
    categories = data.get("category") or []
    news = data.get("news") or []
    rows: list[dict[str, Any]] = []
    for index, cat in enumerate(categories):
        if index >= len(news):
            continue
        rows += [x for x in news[index] if isinstance(x, dict)]
    # 页面 compareDates 按时间倒序(稳定排序,同一时刻保持合并顺序)
    rows.sort(key=lambda x: _timestamp(x.get("p")) or 0, reverse=True)
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        title, link = _text(row.get("t")), str(row.get("l") or "").strip()
        if not title or not link.startswith(("http://", "https://")) or link in seen:
            continue
        seen.add(link)
        m = DOCID_RE.search(link)
        items.append(ListItem(
            id=m.group(1) if m else link,
            title=title,
            url=link,
            mobileUrl=link,
            timestamp=_timestamp(row.get("p")),
        ))
        if len(items) >= LATEST_PAGE_SIZE:
            break
    if not items:
        raise RuntimeError("netease latest board parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}
