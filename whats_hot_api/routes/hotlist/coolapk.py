from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.coolapk import gen_headers

ROUTE_NAME = "coolapk"

type_map: dict[str, str] = {
    "today": "今日热门",
    "headline": "历史头条",
    "reply": "评论榜",
    "kutu": "酷图榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "酷安",
    "description": "酷安 App 的今日热门、历史头条、评论榜、酷图榜。",
    "link": "https://www.coolapk.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_DATA_LIST = "https://api.coolapk.com/v6/page/dataList"
# 需修根因(board_api evidence/06):Chrome UA 一律 403 空响应,UA 必须含 App 标识
# +CoolMarket/…;token 头照 App 算法现算(共享 token 模块)。
_COOLAPK_UA = ("Dalvik/2.1.0 (Linux; U; Android 10; Mi 10 Build/QKQ1.191117.002) "
               "(#Build; Xiaomi; Mi 10; QKQ1.191117.002 test-keys; 10) +CoolMarket/11.0-2101202")
_BOARDS: dict[str, tuple[str, str, str]] = {
    # board: (App 列表地址, 列表标题, 页签名)
    "today": ("#/feed/statList?cacheExpires=300&statType=day&sortField=rank_score"
              "&filterRepeatQuestionAnswer=true&replyRowsLimit=1", "今日热门", "今日热门"),
    "headline": ("#/feed/headlineV8List?type=0,5,9,8,12,10,11,13&title=历史头条", "历史头条", "历史头条"),
    "reply": ("#/feed/statList?statType=day&sortField=replynum", "评论榜", "评论榜（日榜）"),
    "kutu": ("#/feed/statList?statType=30days&sortField=likenum&type=8", "周榜", "酷图榜 · 周榜"),
}
# 今日热门的正确排序是 rank_score(evidence/05:与 App 热榜页逐位相同);
# 旧路由用的 detailnum 是旧参数,顺序已与 App 不同。


def _headers() -> dict[str, str]:
    return {**gen_headers(), "User-Agent": _COOLAPK_UA}


def _plain(fragment: Any, limit: int | None = None) -> str:
    text = BeautifulSoup(str(fragment or ""), "lxml").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def _item(x: dict[str, Any]) -> ListItem:
    text = _plain(x.get("message"))
    title = _plain(x.get("message_title")) or text
    if len(title) > 120:  # 动态没有标题:标题取前 120 字,全文放 desc
        title = title[:120] + "…"
    raw_path = x.get("url")
    path = raw_path if isinstance(raw_path, str) and raw_path.startswith("/") else f"/feed/{x['id']}"
    url = "https://www.coolapk.com" + path  # /feed/<id>;酷图是 /picture/<id>
    pics = [p for p in x.get("picArr") or [] if isinstance(p, str) and p]
    cover = x.get("pic") or (pics[0] if pics else None) or x.get("message_cover") or None
    return ListItem(id=str(x["id"]), title=title, url=url, mobileUrl=url, cover=cover, author=x.get("username"),
                    desc=text[:500] if text and text != title else None, timestamp=x.get("dateline"))


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "today")
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
    list_url, title, _tab = _BOARDS[board]
    url = f"{_DATA_LIST}?url={quote(list_url, safe='')}&title={quote(title)}&page=1"
    result = await get(url=url, headers=_headers(), no_cache=no_cache, response_type="json")
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError(f"coolapk dataList returned no data list: {str(payload)[:200]}")
    items: list[ListItem] = []
    seen: set[str] = set()
    for x in rows:
        # 只取动态;entityType=card 是广告卡片(sponsorCard)等插入位
        if not isinstance(x, dict) or x.get("entityType") != "feed" or not x.get("id"):
            continue
        if str(x["id"]) in seen:
            continue
        seen.add(str(x["id"]))
        items.append(_item(x))
    if not items:
        raise RuntimeError(f"coolapk board '{board}' parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}
