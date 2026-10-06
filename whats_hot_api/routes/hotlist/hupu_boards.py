"""虎扑社区版块 —— 分区热帖、版块 24小时榜 / 最新回复、虎扑首页资讯。

与既有 hupu 路由的边界:hupu 的 topicThreads 1/6/11/12/612 是 m.hupu.com 的"最新回复"流、
home 是社区首页"虎扑社区热帖"(全站);本路由的 14 个列表(分区热帖、恋爱/职场/股票区列表、
首页资讯)它都没有,互不重叠。恋爱区对照:/hupu/6 是 /love 的最新回复,这里是 /love-hot 的 24小时榜。

- 数据全部取自页面服务端渲染时内嵌的 window.$$data JSON(raw_decode 截取),与页面 HTML
  列表逐条同序:
  - 分区热帖 9 个:bbs.hupu.com/all-{分区} 的 pageData.threads。页面缺省的文字列表只渲染
    前 60 条(前端列表组件按 slice(0,10)...slice(50,60) 分 6 段),数据里有 70 条,取前 60
  - 版块列表 4 个:{版块}-hot(24小时榜)与 /stock(最新回复)的 topic.threads.list 第 1 页
  - 资讯 1 个:www.hupu.com 首页"虎扑资讯"栏的 pageData(首屏约 40 条,无限滚动只取首屏)
- 反爬口径:bbs.hupu.com 的阿里云 WAF 拦 python- 开头的 UA(405 拦截页),浏览器 UA 直接 200,
  没有滑块或 JS 挑战;不要换成程序 UA。
- 防回落:不存在的分区地址不 404,而是回落成全站页(已下线的 /all-life 就是这种)。按页面
  返回的分区名 / 版块名与排序(sort:4=24小时榜,2=最新回复)核对,不一致直接报错。
- hot 统一取回复数(三类页面都显示回复数);亮数(lights)、阅读数(read)结构里没有对应字段,丢弃。
- 分区热帖与资讯的数据里没有发帖时间,timestamp 留空;版块列表用 createdAt(毫秒)。
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hupu-boards"

_BBS = "https://bbs.hupu.com"


class _Board(NamedTuple):
    kind: str  # all = 分区热帖,topic = 版块列表,news = 首页虎扑资讯
    page: str  # 页面地址
    label: str  # 榜单标签,写进 RouterData.type
    expect: str  # 页面里应当出现的分区名 / 版块名,用来识别回落页
    sort: int = 0  # 版块列表的排序:4 = 24小时榜,2 = 最新回复


_BOARDS: dict[str, _Board] = {
    "all-gambia": _Board("all", f"{_BBS}/all-gambia", "步行街热帖", "步行街"),
    "all-nba": _Board("all", f"{_BBS}/all-nba", "NBA热帖", "NBA"),
    "all-cba": _Board("all", f"{_BBS}/all-cba", "CBA热帖", "CBA"),
    "all-soccer": _Board("all", f"{_BBS}/all-soccer", "国际足球热帖", "国际足球"),
    "all-csl": _Board("all", f"{_BBS}/all-csl", "中国足球热帖", "中国足球"),
    "all-gg": _Board("all", f"{_BBS}/all-gg", "游戏热帖", "游戏"),
    "all-ent": _Board("all", f"{_BBS}/all-ent", "影视娱乐热帖", "影视娱乐"),
    "all-cars": _Board("all", f"{_BBS}/all-cars", "汽车热帖", "汽车"),
    "all-gear": _Board("all", f"{_BBS}/all-gear", "装备热帖", "装备"),
    "love-hot": _Board("topic", f"{_BBS}/love-hot", "恋爱区 · 24小时榜", "恋爱区", 4),
    "workplace-hot": _Board("topic", f"{_BBS}/workplace-hot", "职场区 · 24小时榜", "职场区", 4),
    "stock-hot": _Board("topic", f"{_BBS}/stock-hot", "股票区 · 24小时榜", "股票区", 4),
    "stock": _Board("topic", f"{_BBS}/stock", "股票区 · 最新回复", "股票区", 2),
    "news": _Board("news", "https://www.hupu.com/", "虎扑资讯", "虎扑资讯"),
}

# 声明序第一个是默认榜
type_map: dict[str, str] = {key: board.label for key, board in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "虎扑社区",
    "description": (
        "虎扑社区分区热帖（步行街、NBA、CBA、足球、游戏、影视娱乐、汽车、装备）、"
        "恋爱 / 职场 / 股票区列表、虎扑首页资讯"
    ),
    "link": f"{_BBS}/",
    "params": {"type": {"name": "分区 / 版块", "type": type_map}},
}

# bbs.hupu.com 的阿里云 WAF 只拦 python- 开头的 UA(405 拦截页),浏览器 UA 直接 200
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}

_TEXT_LIST_LIMIT = 60  # 分区页文字列表(页面缺省视图)只渲染 threads 的前 60 条
_DATA_MARK = "window.$$data"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", next(iter(type_map)))
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    board = _BOARDS[type_param]
    list_data = await _get_board(board, no_cache)
    return RouterData(
        **{
            **ROUTE_META,
            "link": board.page,
            # 资讯来自 www.hupu.com 首页,站点名跟页面走
            "title": "虎扑" if board.kind == "news" else ROUTE_META["title"],
        },
        type=board.label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_board(board: _Board, no_cache: bool) -> dict:
    result = await get(
        url=board.page,
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="text",
    )
    html = str(result.data)
    data = _page_data(html, board.page)
    if board.kind == "all":
        items = _parse_all(data, board)
    elif board.kind == "topic":
        items = _parse_topic(data, board)
    else:
        items = _parse_news(data, html, board)
    if not items:
        raise RuntimeError(f"Hupu board '{board.label}' parsed no items: {board.page}")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _page_data(html: str, page: str) -> dict[str, Any]:
    """截取 `window.$$data = <JSON>` 里的对象(后面紧跟别的脚本语句,用 raw_decode 只取一个)。"""
    mark_at = html.find(_DATA_MARK)
    if mark_at < 0:
        raise RuntimeError(f"Hupu page has no { _DATA_MARK } embedded data: {page}")
    value_at = html.index("=", mark_at + len(_DATA_MARK)) + 1
    data, _ = json.JSONDecoder().raw_decode(html[value_at:].lstrip())
    if not isinstance(data, dict):
        raise RuntimeError(f"Hupu page { _DATA_MARK } is not an object: {page}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    return data


def _parse_all(data: dict[str, Any], board: _Board) -> list[ListItem]:
    page_data = data.get("pageData") or {}
    name = (page_data.get("category") or {}).get("name")
    if name != board.expect:
        # 不存在的分区地址不 404,而是回落成全站页(虎扑社区);已下线的 /all-life 就是这样
        raise RuntimeError(
            f"Hupu page returned category {name!r} instead of {board.expect!r} "
            f"(fallback to site home?): {board.page}"
        )
    threads = page_data.get("threads") or []
    items: list[ListItem] = []
    for thread in threads[:_TEXT_LIST_LIMIT]:
        if not isinstance(thread, dict):
            continue
        items.append(
            _item(
                thread.get("tid"),
                thread.get("title"),
                hot=thread.get("replies"),
                cover=_text(thread.get("cover")),
                desc=_text(thread.get("desc")),
            )
        )
    return [item for item in items if item is not None]


def _parse_topic(data: dict[str, Any], board: _Board) -> list[ListItem]:
    topic = data.get("topic") or {}
    name = (topic.get("topic") or {}).get("name")
    # sort 有时是数字、有时是字符串,统一按字符串比
    if name != board.expect or str(topic.get("sort")) != str(board.sort):
        raise RuntimeError(
            f"Hupu page returned board {name!r} (sort={topic.get('sort')!r}) "
            f"instead of {board.expect!r} (sort={board.sort}): {board.page}"
        )
    rows = (topic.get("threads") or {}).get("list") or []
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        created = row.get("createdAt")
        items.append(
            _item(
                row.get("tid"),
                row.get("title"),
                hot=row.get("replies"),
                cover=_text(row.get("cover")),
                author=_text((row.get("author") or {}).get("puname")),
                timestamp=get_time(created) if isinstance(created, int) and created > 0 else None,
            )
        )
    return [item for item in items if item is not None]


def _parse_news(data: dict[str, Any], html: str, board: _Board) -> list[ListItem]:
    mark_at = max(html.find(_DATA_MARK), 0)
    if "虎扑资讯" not in html[:mark_at]:
        raise RuntimeError(f"Hupu www home page has no '虎扑资讯' section: {board.page}")
    rows = data.get("pageData") or []
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # 资讯标题带 "[流言板]" 等前缀,照原站保留;正文只有日期没有时刻,不编 timestamp
        items.append(
            _item(
                row.get("tid"),
                row.get("title"),
                hot=row.get("replies"),
                cover=_text(row.get("img")),
                desc=_text(row.get("content")),
            )
        )
    return [item for item in items if item is not None]


def _text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _item(tid: Any, title: Any, **extra: Any) -> ListItem | None:
    tid_text = str(tid or "").strip()
    title_text = _text(title)
    if not tid_text.isdigit() or not title_text:
        return None
    url = f"{_BBS}/{tid_text}.html"
    return ListItem(id=tid_text, title=title_text, url=url, mobileUrl=url, **extra)
