from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sina-channels"

type_map: dict[str, str] = {
    "news-roll": "全部滚动新闻",
    "sports-roll": "体育滚动新闻",
    "tech-roll": "科技滚动新闻",
    "tech-csj": "创事记",
    "tech-discovery": "科学探索",
    "tech-apple": "苹果汇",
    "finance-china-roll": "财经国内滚动",
    "finance-estate": "房地产频道",
    "tousu-hot": "黑猫投诉热点追踪",
    "hotnews-comment-all": "评论数排行（全部）",
    "hotnews-comment-china": "国内新闻评论数排行",
    "hotnews-comment-world": "国际新闻评论数排行",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "新浪",
    "description": (
        "新浪栏目：新闻 / 体育 / 科技滚动，创事记、科学探索、苹果汇，"
        "财经国内滚动与房地产频道，黑猫投诉热点追踪，新闻评论数排行。"
    ),
    "link": "https://news.sina.com.cn/roll/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

ROLL_API = "https://feed.mix.sina.com.cn/api/roll/get"
# 子榜 -> (Referer 页面, pageid, lid, 条数, 额外参数);条数照页面首次加载
ROLL_FEEDS: dict[str, tuple[str, str, str, int, dict[str, str]]] = {
    "news-roll": ("https://news.sina.com.cn/roll/", "153", "2509", 50, {"k": ""}),
    "sports-roll": ("https://sports.sina.com.cn/roll/", "13", "2503", 50, {"k": ""}),
    "tech-roll": ("https://tech.sina.com.cn/roll/", "372", "2431", 50, {"k": ""}),
    "tech-csj": ("https://tech.sina.com.cn/chuangshiji/", "402", "2559", 20, {"versionNumber": "1.2.8"}),
    "tech-discovery": ("https://tech.sina.com.cn/discovery/", "207", "1795", 30, {"versionNumber": "1.2.8"}),
    "tech-apple": ("https://tech.sina.com.cn/apple/", "216", "1817", 30, {"versionNumber": "1.2.8"}),
    "finance-china-roll": ("https://finance.sina.com.cn/china/", "155", "1686", 10, {}),
}
ESTATE_PAGE = "https://finance.sina.com.cn/stock/estate/"
ESTATE_API = "https://interface.sina.cn/pc_api/public_news_data.d.json"
ESTATE_PARAMS = {
    "cids": "249945,248786", "pdps": "", "smartFlow": "", "editLevel": "0,1,2,3,4,6,99",
    "type": "std_news,std_slide,std_video", "pageSize": "20", "mod": "nt_category_finance_fund_hot", "cTime": "1483200000",
}
TOUSU_PAGE = "https://tousu.sina.com.cn/articles/index"
TOUSU_API = "https://tousu.sina.com.cn/api/articles/feed"
HOTNEWS_PAGE = "https://news.sina.com.cn/hotnews/"
TOP_API = "https://top.news.sina.com.cn/ws/GetTopDataList.php"
COMMENT_RANKS: dict[str, tuple[str, int, str]] = {
    "hotnews-comment-all": ("qbpdpl", 100, "comment_all_data"),
    "hotnews-comment-china": ("gnxwpl", 20, "news_"),
    "hotnews-comment-world": ("gjxwpl", 20, "news_"),
}
HOTNEWS_SHOWN = 10  # 页面脚本 if(j>9) break:每个榜只显示前 10 条
BEIJING = timezone(timedelta(hours=8))


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _int(value: Any) -> int | None:
    digits = str(value or "").replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def _abs(url: Any) -> str | None:
    u = str(url or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    return u if u.startswith(("http://", "https://")) else None


def _bj_timestamp(value: str, fmt: str) -> int | None:
    try:
        return get_time(int(datetime.strptime(value.strip(), fmt).replace(tzinfo=BEIJING).timestamp()))
    except (AttributeError, ValueError):
        return None


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "news-roll")
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
        message=list_data.get("message"),
    )


async def _get_list(board: str, no_cache: bool) -> dict:
    if board in ROLL_FEEDS:
        return await _fetch_roll(board, no_cache)
    if board == "finance-estate":
        return await _fetch_estate(no_cache)
    if board == "tousu-hot":
        return await _fetch_tousu(no_cache)
    return await _fetch_comment_rank(board, no_cache)


async def _fetch_roll(board: str, no_cache: bool) -> dict:
    page, pageid, lid, num, extra = ROLL_FEEDS[board]
    query = {"pageid": pageid, "lid": lid, **extra, "num": str(num), "page": "1"}
    result = await get(
        url=f"{ROLL_API}?{urlencode(query)}",
        headers={"Referer": page},
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = ((payload.get("result") or {}) if isinstance(payload.get("result"), dict) else {}).get("data")
    if not isinstance(rows, list):
        raise RuntimeError(f"sina roll feed returned no data: pageid={pageid} lid={lid}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, url = _text(row.get("title")), _abs(row.get("url"))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        img = row.get("img") if isinstance(row.get("img"), dict) else {}
        items.append(ListItem(
            id=str(row.get("docid") or url),
            title=title,
            url=url,
            mobileUrl=_abs(row.get("wapurl")) or url,
            cover=_abs(img.get("u")),
            author=_text(row.get("media_name")) or _text(row.get("author")) or None,
            desc=_text(row.get("intro") or row.get("summary")) or None,
            timestamp=int(row["ctime"]) if str(row.get("ctime") or "").isdigit() else None,
        ))
    if not items:
        raise RuntimeError(f"sina roll feed '{board}' parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _fetch_estate(no_cache: bool) -> dict:
    result = await get(
        url=f"{ESTATE_API}?{urlencode(ESTATE_PARAMS)}",
        headers={"Referer": ESTATE_PAGE},
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError(f"sina estate feed returned no data: {payload.get('status')}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, url = _text(row.get("title")), _abs(row.get("url") or row.get("pcurl"))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        items.append(ListItem(
            id=str(row.get("docid") or url),
            title=title,
            url=url,
            mobileUrl=_abs(row.get("wapurl")) or url,
            cover=_abs(row.get("thumb")),
            author=_text(row.get("media")) or _text(row.get("author")) or None,
            desc=_text(row.get("intro") or row.get("summary")) or None,
            hot=row.get("comment_count") or None,
            timestamp=row.get("ctime") if isinstance(row.get("ctime"), int) else None,
        ))
    if not items:
        raise RuntimeError("sina estate feed parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _fetch_tousu(no_cache: bool) -> dict:
    query = {"type": "0", "hot": "1", "page_size": "10", "page": "1"}
    result = await get(
        url=f"{TOUSU_API}?{urlencode(query)}",
        headers={"Referer": TOUSU_PAGE},
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    result_obj = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    status = result_obj.get("status") if isinstance(result_obj.get("status"), dict) else {}
    rows = ((result_obj.get("data") or {}).get("articles")) if isinstance(result_obj.get("data"), dict) else None
    if status.get("code") != 0 or not isinstance(rows, list):
        raise RuntimeError(f"sina tousu feed returned abnormal status: {status}")
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, url = _text(row.get("title")), _abs(row.get("url"))
        if not title or not url:
            continue
        items.append(ListItem(
            id=str(row.get("id") or url),
            title=title,
            url=url,
            mobileUrl=url,
            cover=_abs(row.get("cover")),
            author=_text(row.get("media")) or _text(row.get("creator")) or None,
            timestamp=_bj_timestamp(str(row.get("time") or ""), "%Y.%m.%d %H:%M"),
        ))
    if not items:
        raise RuntimeError("sina tousu feed parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _page_filter_all(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """照 hotnews 页"评论数排行(全部)"的显示脚本逐条筛,最多 10 条(变量名与页面一致)。"""
    s_cnt = e_cnt = f_cnt = 0
    shown: list[dict[str, Any]] = []
    for row in rows:
        if len(shown) >= HOTNEWS_SHOWN:
            break
        url = str(row.get("url") or "")
        if "sports.sina.com.cn" in url or "2012.sina.com.cn" in url:
            if s_cnt > 3:
                continue
            s_cnt += 1
        if "ent.sina.com.cn" in url:
            if e_cnt > 1:
                continue
            e_cnt += 1
        if "tech.sina.com.cn" in url:
            if e_cnt > 20:
                continue
            e_cnt += 1
        if "finance.sina.com.cn" in url:
            if f_cnt > 5:
                continue
            f_cnt += 1
        if not any(d in url for d in ("sports.sina.com.cn", "2012.sina.com.cn", "ent.sina.com.cn", "tech.sina.com.cn",
                                      "finance.sina.com.cn", "news.sina.com.cn", "mil.news.sina.com.cn")):
            continue
        if "news.sina.com.cn/s/" in url or "/bbs/" in url:
            continue
        shown.append(row)
    return shown


async def _fetch_comment_rank(board: str, no_cache: bool) -> dict:
    cat, show_num, js_var = COMMENT_RANKS[board]
    day = datetime.now(BEIJING).strftime("%Y%m%d")  # 页面按北京时间写 top_time
    query = {"top_type": "day", "top_cat": cat, "top_time": day, "top_show_num": str(show_num),
             "top_order": "DESC", "js_var": js_var}
    result = await get(
        url=f"{TOP_API}?{urlencode(query)}",
        headers={"Referer": HOTNEWS_PAGE},
        no_cache=no_cache,
        response_type="text",
    )
    text = str(result.data).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"sina comment rank returned unexpected format: {text[:120]}")
    rows = [x for x in (json.loads(text[start:end + 1]).get("data") or []) if isinstance(x, dict)]
    rows = _page_filter_all(rows) if board == "hotnews-comment-all" else rows[:HOTNEWS_SHOWN]
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        title, url = _text(row.get("title")), _abs(row.get("url"))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        items.append(ListItem(
            id=url,
            title=title,
            url=url,
            mobileUrl=url,
            hot=_int(row.get("top_num")),
            author=_text(row.get("media")) or _text(row.get("author")) or None,
            cover=_abs(row.get("ext2")),
            timestamp=_bj_timestamp(f"{row.get('create_date')} {row.get('create_time')}", "%Y-%m-%d %H:%M:%S"),
        ))
    message = None
    if not items:
        # 北京时间刚过 0 点时当天的日榜可能还是空的(页面同样显示空表)
        message = f"{day} 的日榜暂无数据"
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items, "message": message}
