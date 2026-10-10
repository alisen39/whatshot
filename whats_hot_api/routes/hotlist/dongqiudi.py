"""懂球帝(dongqiudi)。

数据源与口径照 board_api 证据 tmp/board_api/dongqiudi(2026-09-30 冷启动留档,
纯 HTTP 直连、公开 JSON 接口,不需要登录、cookie、签名;每个子榜 1 个请求):
- m 站首页频道页签 m.dongqiudi.com/home/<tab>(头条 1、德甲 6、深度 55、中超 56、热门 104):
  页面 SSR 与翻页都用 api.dongqiudi.com/app/tabs/iphone/<tab>.json?mark=gif&version=576
  (地址写在 m 站 homeSubTabList 里),取第 1 页,照接口顺序(置顶在前)。
  热门(104)的条目按天分组在 contents[].articles,按组顺序展开;web 版 tabs/web/104.json
  结构不同(contents 平铺、无 articles),PC 首页"热门"页签按 articles 取显示为空,故取 iphone 版。
- 头条新闻(PC 首页"推荐"页签):www.dongqiudi.com/api/app/tabs/web/1.json,与 m 站头条同一份列表。
  PC 页面把评论数最多的一条(脚本先找 is_top,接口没有这个字段所以找不到)拿到最上面做大图头条,
  其余照接口顺序排成网格;本路由照页面顺序输出。
- 球队资讯(AC米兰 50001038、山东泰山 50000335):PC 球队页 SSR 调
  /api/v3/archive/app/channel/feeds?id=<id>&type=team&size=30&platform=web&version=;
  platform=web 必需(不带返回另一份未按 web 过滤的列表),size=30 与页面一致。
- 早报:PC 专题页 /special/48 背后的 /api/old/columns/48 第 1 页(20 条)。
反爬:www.dongqiudi.com 对程序 UA(curl、python-httpx)返回 HTTP 567 拦截页,
必须带浏览器 UA(verify/header_matrix.md);Referer 实测非必需,不带。
timestamp 取 show_time(真实发布时间;置顶条的 published_at 被改成未来年份排序,不用),
晚于当前时间的值一律留空。
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "dongqiudi"

_PC = "https://www.dongqiudi.com"
_M = "https://m.dongqiudi.com"
_API = "https://api.dongqiudi.com"

# 子榜键 -> (中文名, 取数方式, 参数);声明序第一个是默认榜
_BOARDS: dict[str, tuple[str, str, str]] = {
    "headline": ("头条新闻（PC 首页推荐）", "pc_tab", "1"),
    "headline-app": ("今日头条（m 站头条）", "m_tab", "1"),
    "bundesliga": ("德甲", "m_tab", "6"),
    "depth": ("深度", "m_tab", "55"),
    "csl": ("中超", "m_tab", "56"),
    "hot": ("热门", "m_tab", "104"),
    "team-acmilan": ("AC米兰", "team", "50001038"),
    "team-shandong-taishan": ("山东泰山（原山东鲁能泰山）", "team", "50000335"),
    "morning": ("早报", "column", "48"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "懂球帝",
    "description": "懂球帝：首页头条、德甲 / 深度 / 中超 / 热门频道、AC米兰与山东泰山球队资讯、早报专题。",
    "link": f"{_PC}/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = "headline"

_HEADERS = {
    # www.dongqiudi.com 对程序 UA 返回 567 拦截页,必须带浏览器 UA
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}

# m 站 homeSubTabList 里接口地址自带的参数(实测非必需,照页面带上)
_M_TAB_PARAMS: dict[str, str] = {"mark": "gif", "version": "576"}
_TEAM_PAGE_SIZE = 30  # PC 球队页 SSR 的 size(页面 newsNextUrl 同样是 size=30)


def _request_plan(board: str) -> tuple[str, dict[str, str]]:
    """(接口地址, query 参数)。Referer 实测非必需,不带。"""
    _, kind, arg = _BOARDS[board]
    if kind == "m_tab":
        return f"{_API}/app/tabs/iphone/{arg}.json", _M_TAB_PARAMS
    if kind == "pc_tab":
        return f"{_PC}/api/app/tabs/web/{arg}.json", {}
    if kind == "team":
        return f"{_PC}/api/v3/archive/app/channel/feeds", {
            "id": arg,
            "type": "team",
            "size": str(_TEAM_PAGE_SIZE),
            "platform": "web",
            "version": "",
        }
    return f"{_PC}/api/old/columns/{arg}", {}


def _timestamp(value: Any) -> int | None:
    """show_time(Unix 秒);晚于当前时间(置顶排序用的未来值)或无效时留空。"""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return ts if 0 < ts <= time.time() + 600 else None


def _author(row: dict[str, Any]) -> str | None:
    author = row.get("author")
    name = author.get("name") if isinstance(author, dict) else None
    return (str(row.get("author_name") or name or row.get("writer") or "").strip()) or None


def _rows(board: str, payload: Any) -> list[dict[str, Any]]:
    """从接口响应取条目数组;热门(104)的 contents 按天分组,按组顺序展开。"""
    kind = _BOARDS[board][1]
    if not isinstance(payload, dict):
        return []
    if kind == "team":
        data = payload.get("data")
        return list(data.get("articles") or []) if isinstance(data, dict) else []
    if kind == "column":
        return list(payload.get("data") or [])
    if kind == "m_tab" and payload.get("contents") and not payload.get("articles"):
        return [
            row
            for group in payload["contents"]
            if isinstance(group, dict)
            for row in group.get("articles") or []
        ]
    return list(payload.get("articles") or [])


def _pc_home_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PC 首页(home-new)的显示顺序:headlineArticle 在最上面,其余(feedCards)照接口顺序。

    页面脚本:headline 取第一条 isTop(映射自 is_top,接口没有这个字段),否则评论数最多的
    一条(稳定排序,并列取靠前的)。
    """
    if not rows:
        return rows
    head = next((row for row in rows if row.get("is_top")), None)
    if head is None:
        head = max(rows, key=lambda row: int(row.get("comments_total") or 0))
    return [head] + [row for row in rows if row is not head]


def _item(row: dict[str, Any], pc_link: bool) -> ListItem | None:
    item_id = str(row.get("id") or row.get("aid") or "").strip()
    title = str(row.get("title") or "").strip()
    if not item_id or not title:
        return None
    pc_url = f"{_PC}/articles/{item_id}.html"
    share = str(row.get("share") or "")
    # m 站 / App 的分享链接是 www.dongqiudi.com/article/<id>(与 tophub 同形);
    # 海报类(mini_top)的 share 是 n.dongqiudi.com 的 H5 页,改用 PC 链接
    url = pc_url if pc_link or not share.startswith(_PC + "/") else share
    return ListItem(
        id=item_id,
        title=title,
        url=url,
        mobileUrl=f"{_M}/article/{item_id}.html",
        cover=row.get("thumb") or row.get("litpic") or None,
        author=_author(row),
        desc=str(row.get("description") or "").strip() or None,
        metrics={"comments": count} if (count := _positive_int(row.get("comments_total"))) else None,
        timestamp=_timestamp(row.get("show_time")),
    )


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", DEFAULT_TYPE)
    if board not in _BOARDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    label, kind, _ = _BOARDS[board]
    url, params = _request_plan(board)
    result = await get(
        url=url,
        params=params,
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="json",
    )
    rows = [row for row in _rows(board, result.data) if isinstance(row, dict)]
    if kind == "pc_tab":
        rows = _pc_home_order(rows)
    pc_link = kind in ("pc_tab", "team", "column")
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        item = _item(row, pc_link)
        if item is not None and item.id not in seen:
            seen.add(item.id)
            items.append(item)
    if not items:
        raise RuntimeError(f"dongqiudi {board} parsed no items from {url}")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
