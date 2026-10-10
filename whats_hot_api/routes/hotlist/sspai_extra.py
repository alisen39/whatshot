"""少数派栏目（type=栏目）。

迁移自 board_api sspai_coolapk 单元（7 个少数派榜；酷安 4 榜已修回既有 /coolapk 路由），每个子榜 1 个请求：
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
     与 App 一致，这里复用并只覆盖 UA
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

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sspai-extra"

_TYPE_MAP: dict[str, str] = {
    "sspai-latest": "少数派 · 最新文章",
    "sspai-zaobao": "少数派 · #派早报",
    "sspai-paiping": "少数派 · #派评",
    "sspai-matrix": "少数派 · Matrix",
    "sspai-matrix-hot": "少数派 · Matrix热榜",
    "sspai-bullet": "少数派 · 一派话题广场",
    "sspai-series": "少数派 · 最新上架付费专栏",
}

_DEFAULT_TYPE = "sspai-latest"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "少数派",
    "description": "少数派的标签、Matrix、一派、付费栏目与首页文章流（酷安榜已修回 /coolapk 路由）。",
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


def _corner_badge(row: dict[str, Any]) -> list[dict]:
    # corner 角标只认 name 文案;icon 不是 http(s) 链接时不带图
    corner = row.get("corner") if isinstance(row.get("corner"), dict) else {}
    name = str(corner.get("name") or "").strip()
    if not name:
        return []
    icon = str(corner.get("icon") or "").strip()
    if icon.startswith(("http://", "https://")):
        return [{"text": name, "imageUrl": icon}]
    return [{"text": name}]


def _count_metrics(row: dict[str, Any]) -> dict[str, int] | None:
    # 计数只收正整数;一派/专栏条目没有这些字段,不进 metrics
    metrics: dict[str, int] = {}
    for source_key, metric_key in (("view_count", "views"), ("comment_count", "comments"), ("like_count", "likes")):
        value = row.get(source_key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            metrics[metric_key] = value
    return metrics or None


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
        badges=_corner_badge(row),
        metrics=_count_metrics(row),
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



async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "sspai-latest")
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _get_sspai(board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=f"{_TYPE_MAP[board]}（{list_data['list_name']}）",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )
