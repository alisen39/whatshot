"""少数派与酷安（多站点，type=站点-栏目）。

迁移自 board_api sspai_coolapk 单元（11 个已完成榜），每个子榜 1 个请求：
- 少数派：sspai.com/api/v1 公开接口，无签名、无 cookie（curl/httpx 缺省 UA 均 200）。
  参数与条数取自前端页面脚本（post.sspai.com 的 main / tag-item / matrix-hot / series-home），
  页面服务端渲染的首屏与接口逐条相同（board_api verify/page_vs_api.md）：
  - #派早报 / #派评：``/article/tag/page/get?tag=<标签>``，tag 页首屏 limit=12
  - Matrix（精选）：``/article/matrix/page/get``；Matrix 热榜：``/article/matrix/hot/page/get``（limit=20）
  - 一派话题广场：``/bullet/search/page/get``（/matrix/pods 页，limit=10）。
    条目没有 id 字段，页面链接就是 ``/bullet/<created_at>``；列表按 ``released_at`` 倒序
  - 最新上架付费专栏：``/series/search/page/get?sort=weight``（/series 页「最新上架」区块，limit=5）
  - 最新文章：``/article/index/page/get``（首页文章流，limit=10）。首页前端
    ``adjustLeadingImportantArticle`` 把第 1 篇大卡片（important=2）与后面第一篇普通文章对调，
    本路由照做以还原页面顺序；带 ``advertisement_url`` 的广告卡片不算条目
- 酷安：App 自己的接口 api.coolapk.com/v6（列表统一走 ``page/dataList?url=<App 列表地址>``）。
  whatshot 既有 coolapk 路由的两个需修点，本路由均按 board_api 证据修复：
  1. UA 必须是 App 的 Dalvik UA（含 ``+CoolMarket/11.0-2101202`` 标识）：Chrome 移动 UA 与桌面
     Chrome UA 都返回 403 空响应（evidence/06_coolapk_chrome_ua）；既有路由的 token 算法本身
     与 App 一致，这里复用并只覆盖 UA
  2. 今日热门的列表地址用 App 现行的 ``sortField=rank_score``（热榜页选择器第 1 项，
     evidence/05_coolapk_ranking_page）；既有路由的 ``detailnum`` 是旧参数，顺序已与 App 不同
  - 历史头条：``#/feed/headlineV8List?type=0,5,9,8,12,10,11,13&title=历史头条``。App 11.0 配置里
    没有同名入口；tophub 的 4 个酷安榜名与 RSSHub 酷安路由标题一字不差，RSSHub 的「历史头条」
    即该地址，快照动态经 /v6/feed/detail 查证均为 is_headline=1（analysis_report.md 2.3）。
    该列表几分钟整页轮换，每次取到的是当下这一批头条
  - 评论榜：``statField=replynum``（App 已无入口，接口仍按天更新，按"页面不显示、接口仍更新"做）
  - 酷图榜：热榜页「酷图榜」V10_KUTU_TOP 缺省 tab「周榜」``statType=30days&sortField=likenum&type=8``
  列表里的广告卡片（entityType=card，如 sponsorCard）不算条目；酷安榜单不按显示数字排序，hot 留空。
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.coolapk import gen_headers

ROUTE_NAME = "sspai-coolapk"

_TYPE_MAP: dict[str, str] = {
    "sspai-latest": "少数派 · 最新文章",
    "sspai-zaobao": "少数派 · #派早报",
    "sspai-paiping": "少数派 · #派评",
    "sspai-matrix": "少数派 · Matrix",
    "sspai-matrix-hot": "少数派 · Matrix热榜",
    "sspai-bullet": "少数派 · 一派话题广场",
    "sspai-series": "少数派 · 最新上架付费专栏",
    "coolapk-today": "酷安 · 今日热门",
    "coolapk-headline": "酷安 · 历史头条",
    "coolapk-reply": "酷安 · 评论榜",
    "coolapk-kutu": "酷安 · 酷图榜",
}

_DEFAULT_TYPE = "sspai-latest"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "少数派与酷安",
    "description": "少数派的标签、Matrix、一派、付费栏目与首页文章流；酷安 App 的今日热门、历史头条、评论榜、酷图榜。",
    "link": "https://sspai.com/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_JSON_ACCEPT = "application/json, text/plain, */*"

# ---------------------------------------------------------------- 少数派

_SSPAI_API = "https://sspai.com/api/v1"
_SSPAI_CDN = "https://cdnfile.sspai.com/"  # 页面脚本 main.js 的 cdn.images
# 子榜 -> (接口路径, 固定 query, 是否带 created_at=当前秒[页面用 window.GLOBAL_TIMESTAMP], 列表名)。
# limit 与前端页面首屏一致：tag 12、Matrix 20、一派 10、付费栏目 5、首页 10
_SSPAI_BOARDS: dict[str, tuple[str, dict[str, str], bool, str]] = {
    "sspai-zaobao": ("/article/tag/page/get", {"limit": "12", "offset": "0", "tag": "派早报"}, False, "#派早报"),
    "sspai-paiping": ("/article/tag/page/get", {"limit": "12", "offset": "0", "tag": "派评"}, False, "#派评"),
    "sspai-matrix": ("/article/matrix/page/get", {"limit": "20", "offset": "0"}, True, "Matrix 精选"),
    "sspai-matrix-hot": ("/article/matrix/hot/page/get", {"limit": "20", "offset": "0"}, True, "Matrix 热门"),
    "sspai-bullet": ("/bullet/search/page/get", {"limit": "10", "offset": "0"}, True, "一派话题广场"),
    "sspai-series": (
        "/series/search/page/get",
        {"limit": "5", "offset": "0", "sort": "weight", "released_at": "0", "title": ""},
        False,
        "最新上架",
    ),
    "sspai-latest": ("/article/index/page/get", {"limit": "10", "offset": "0", "created_at": "0"}, False, "首页最新文章"),
}


def _plain(fragment: Any, limit: int | None = None) -> str:
    """HTML 片段转纯文本（一派 body、酷安 message 等字段带内联标签）。"""
    text = BeautifulSoup(str(fragment or ""), "lxml").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def _sspai_cover(path: Any) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    return path if path.startswith("http") else _SSPAI_CDN + path.lstrip("/")


def _sspai_article(row: dict[str, Any]) -> ListItem | None:
    if row.get("advertisement_url"):  # 广告位：卡片链到广告地址，不算条目
        return None
    # 链接与前端文章卡片一致：会员文章 /prime/story/<slug>，其余 /post/<id>
    if row.get("belong_to_member") and row.get("slug"):
        url = f"https://sspai.com/prime/story/{row['slug']}"
    else:
        url = f"https://sspai.com/post/{row['id']}"
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    return ListItem(
        id=row["id"],
        title=_plain(row.get("title")),
        url=url,
        mobileUrl=url,
        hot=row.get("like_count"),
        cover=_sspai_cover(row.get("banner")),
        author=author.get("nickname"),
        desc=_plain(row.get("summary"), 500) or None,
        timestamp=get_time(row.get("released_time")),
    )


def _sspai_bullet(row: dict[str, Any]) -> ListItem:
    created = row["created_at"]  # 一派没有 id 字段，页面链接 /bullet/<created_at>
    url = f"https://sspai.com/bullet/{created}"
    authors = [a for a in row.get("authors") or [] if isinstance(a, dict)]
    return ListItem(
        id=created,
        title=_plain(row.get("title")),
        url=url,
        mobileUrl=url,
        hot=row.get("participations_count"),  # 页面显示「N 位少数派已参与」
        cover=_sspai_cover(row.get("banner")),
        author=authors[0].get("nickname") if authors else None,
        desc=_plain(row.get("body"), 500) or None,
        timestamp=get_time(row.get("released_at")),  # 列表按 released_at 倒序
    )


def _sspai_series(row: dict[str, Any]) -> ListItem:
    url = row.get("page_redirect_url") or f"https://sspai.com/series/{row['id']}"
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    return ListItem(
        id=row["id"],
        title=_plain(row.get("title")),
        url=url,
        mobileUrl=url,
        cover=_sspai_cover(row.get("banner")),
        author=author.get("nickname"),
        desc=_plain(row.get("description"), 500) or None,
        timestamp=get_time(row.get("released_at")),  # 上架时间
    )


def _adjust_leading_important(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """首页前端 adjustLeadingImportantArticle：第 1 篇是大卡片（important=2）时，
    与后面第一篇非大卡片文章对调，使接口顺序与页面一致。"""
    rows = list(rows)
    if len(rows) >= 2 and rows[0].get("important") == 2:
        index = next((k for k in range(1, len(rows)) if rows[k].get("important") != 2), 0)
        if index > 0:
            rows[0], rows[index] = rows[index], rows[0]
    return rows


async def _get_sspai(board: str, no_cache: bool) -> dict:
    path, params, with_timestamp, list_name = _SSPAI_BOARDS[board]
    query = dict(params)
    if with_timestamp:
        query["created_at"] = str(int(time.time()))
    result = await get(
        url=f"{_SSPAI_API}{path}",
        params=query,
        headers={"Accept": _JSON_ACCEPT},
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("error") != 0 or not isinstance(payload.get("data"), list):
        # 严格拒绝业务错误壳（error != 0）与变形响应，不降级为空榜
        raise RuntimeError(f"sspai {path} returned error={payload.get('error')} (non-list data): {str(payload)[:200]}")
    rows = [row for row in payload["data"] if isinstance(row, dict)]
    if board == "sspai-bullet":
        items = [_sspai_bullet(row) for row in rows]
    elif board == "sspai-series":
        items = [_sspai_series(row) for row in rows]
    else:
        if board == "sspai-latest":
            rows = _adjust_leading_important(rows)
        items = [item for row in rows if (item := _sspai_article(row))]
    if not items:
        raise RuntimeError(f"sspai {path} board '{board}' returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items, "list_name": list_name}


# ---------------------------------------------------------------- 酷安

_COOLAPK_API = "https://api.coolapk.com/v6/page/dataList"
# App 的 Dalvik UA（需修点）：服务端按 UA 里的 +CoolMarket/<版本> 标识放行，
# Chrome 移动 / 桌面 UA 都是 403 空响应；版本号与 X-App-Version / X-App-Code 一致
_COOLAPK_UA = (
    "Dalvik/2.1.0 (Linux; U; Android 10; Mi 10 Build/QKQ1.191117.002) "
    "(#Build; Xiaomi; Mi 10; QKQ1.191117.002 test-keys; 10) +CoolMarket/11.0-2101202"
)
# 子榜 -> (App 列表地址（dataList 的 url 参数，取自 App 页面配置）, 页面标题, 列表名)
_COOLAPK_BOARDS: dict[str, tuple[str, str, str]] = {
    "coolapk-today": (
        ("#/feed/statList?cacheExpires=300&statType=day&sortField=rank_score" "&filterRepeatQuestionAnswer=true&replyRowsLimit=1"),
        "今日热门",
        "今日热门",
    ),
    "coolapk-headline": ("#/feed/headlineV8List?type=0,5,9,8,12,10,11,13&title=历史头条", "历史头条", "历史头条"),
    "coolapk-reply": ("#/feed/statList?statType=day&sortField=replynum", "评论榜", "评论榜（日榜）"),
    "coolapk-kutu": ("#/feed/statList?statType=30days&sortField=likenum&type=8", "周榜", "酷图榜 · 周榜"),
}


def _coolapk_headers() -> dict[str, str]:
    """App 请求头：token 等按既有 App 算法现算（每次调用重新生成），UA 覆盖为 App 的 Dalvik UA。"""
    return {**gen_headers(), "User-Agent": _COOLAPK_UA}


def _coolapk_url(board: str) -> str:
    """App 打开列表页的方式：page/dataList?url=<列表地址>&title=<标题>&page=1。"""
    list_url, title, _ = _COOLAPK_BOARDS[board]
    return f"{_COOLAPK_API}?url={quote(list_url, safe='')}&title={quote(title)}&page=1"


def _coolapk_item(row: dict[str, Any]) -> ListItem:
    text = _plain(row.get("message"))
    title = _plain(row.get("message_title")) or text
    if len(title) > 120:  # 动态没有标题，正文可能上千字：标题取前 120 字，全文放 desc
        title = title[:120] + "…"
    raw_path = row.get("url")
    path = raw_path if isinstance(raw_path, str) and raw_path.startswith("/") else f"/feed/{row['id']}"
    url = "https://www.coolapk.com" + path  # /feed/<id>；酷图是 /picture/<id>
    pics = [p for p in row.get("picArr") or [] if isinstance(p, str) and p]
    cover = row.get("pic") or (pics[0] if pics else None) or row.get("message_cover") or None
    return ListItem(
        id=row["id"],
        title=title,
        url=url,
        mobileUrl=url,
        cover=cover,
        author=row.get("username"),
        desc=text[:500] if text and text != title else None,
        timestamp=get_time(row.get("dateline")),
    )


async def _get_coolapk(board: str, no_cache: bool) -> dict:
    result = await get(
        url=_coolapk_url(board),
        headers=_coolapk_headers(),
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    rows = result.data.get("data") if isinstance(result.data, dict) else None
    if not isinstance(rows, list):
        # 严格拒绝变形响应（UA / token 失效时服务端返回 403 空响应或 status=1001/1004/1005 的壳）
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"coolapk dataList '{board}' has no data list: {str(result.data)[:200]}"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        # 只取动态；entityType=card 是广告卡片（sponsorCard）等插入位
        if not isinstance(row, dict) or row.get("entityType") != "feed" or not row.get("id"):
            continue
        if str(row["id"]) in seen:
            continue
        seen.add(str(row["id"]))
        items.append(_coolapk_item(row))
    if not items:
        raise RuntimeError(f"coolapk dataList '{board}' returned no feed items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "list_name": _COOLAPK_BOARDS[board][2],
    }


# ---------------------------------------------------------------- 入口


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await (_get_sspai(board, no_cache) if board in _SSPAI_BOARDS else _get_coolapk(board, no_cache))
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=f"{_TYPE_MAP[board]}（{list_data['list_name']}）",
    )
