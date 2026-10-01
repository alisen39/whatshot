"""GitHub 周刊仓库(4 个子榜:Releases / Issues)。

与既有 GitHub 路由的边界:github 路由取 GitHub 官方 Blog 与 tophub 风格的仓库热榜,
github-trending-lang 取 /trending 页;本路由取 4 个"按期发布"的周刊仓库的
Releases / Issues 列表,来源不重叠。子榜与仓库的对应关系照 board_api 证据
(tophub 节点条目链接指向哪个仓库就取哪个仓库):

- d2-daily      -> d2-projects/d2-daily 的 Releases(已停更,最后一期 2019-09-03 第 170 期,
                   tophub 同样停在该期;照原站当前列表输出)
- fe-weekly     -> ascoders/weekly 的 Releases(缺省榜)
- ios-weekly    -> SwiftOldDriver/iOS-Weekly 的 Releases
- hackernews-weekly -> headllines/hackernews-weekly 的 open Issues(机器人每周一开一个)

取数不调 GitHub REST API(避免未登录每小时 60 次限制):
- Releases 用官方 Atom feed releases.atom(固定最近 10 条),解析与 claude-code-releases 路由相同
- 该 Issues 仓库没有官方 feed(README 里的 RSS 是第三方 rsshub.app),改取 Issues 列表页
  服务端渲染的内嵌 JSON(react-app.embeddedData),取原站第 1 页 25 条(列表默认筛选
  is:issue state:open sort:created-desc)

反爬:无。UA / cookie 均不校验(实测 curl 缺省 UA 响应逐字节相同),仍按站点惯例带浏览器 UA。
id 用上游稳定标识(Atom entry id / Issue 编号,禁名次);timestamp 统一毫秒。
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "github-weekly-repos"

# 子榜键 -> (榜名, 仓库, 取数方式)。fe-weekly 是 board_api 的缺省榜,声明序第一个即默认榜
_BOARDS: dict[str, tuple[str, str, str]] = {
    "fe-weekly": ("前端精读周刊", "ascoders/weekly", "releases"),
    "d2-daily": ("D2-daily", "d2-projects/d2-daily", "releases"),
    "ios-weekly": ("老司机 iOS 周报", "SwiftOldDriver/iOS-Weekly", "releases"),
    "hackernews-weekly": ("Headllines/hackernews Weekly Issues", "headllines/hackernews-weekly", "issues"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "GitHub 周刊仓库",
    "description": "GitHub 上按期发布的周刊 / 日刊仓库:D2-daily、前端精读周刊、老司机 iOS 周报、hackernews Weekly Issues。",
    "link": "https://github.com/",
    "params": {
        "type": {
            "name": "周刊",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = next(iter(type_map))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}
_FEED_HEADERS = {**_HEADERS, "Accept": "application/atom+xml, application/xml, text/xml"}
_HTML_HEADERS = {**_HEADERS, "Accept": "text/html,application/xhtml+xml"}
# Issues 列表页内嵌 JSON 的 script 标签
_EMBEDDED = re.compile(
    r'<script type="application/json" data-target="react-app.embeddedData">(.*?)</script>',
    re.DOTALL,
)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, repo, kind = _BOARDS[type_param]
    list_data = await _get_list(label, repo, kind, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": list_data["link"]},
        type=f"{label} · {'Releases' if kind == 'releases' else 'Issues'}",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(label: str, repo: str, kind: str, no_cache: bool) -> dict:
    if kind == "releases":
        # releases.atom 是 GitHub 长期提供的官方 feed,固定最近 10 条
        result = await get(
            url=f"https://github.com/{repo}/releases.atom",
            headers=_FEED_HEADERS,
            response_type="text",
            no_cache=no_cache,
        )
        # 拿到 HTML(登录页 / 错误页)时明确报错,不静默输出空榜
        if "<feed" not in result.data:
            raise RuntimeError(f"{repo} releases.atom is not an Atom document (page changed?)")
        items = parse_feed(result.data)
        link = f"https://github.com/{repo}/releases"
    else:
        result = await get(
            url=f"https://github.com/{repo}/issues",
            params={"page": 1},  # 列表每页 25 条,照原站取第 1 页
            headers=_HTML_HEADERS,
            response_type="text",
            no_cache=no_cache,
        )
        items = _issue_items(result.data, repo)
        link = f"https://github.com/{repo}/issues"
    if not items:
        raise RuntimeError(f"{repo} {kind} returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "link": link,
    }


def _issue_items(page: str, repo: str) -> list[ListItem]:
    """Issues 列表页内嵌 JSON:payload.preloadedQueries[0].result.data.repository.search.edges[].node。

    列表只含 open 的 Issue,按创建时间倒序;列表页不含正文,所以没有 desc / hot / cover。
    """
    items: list[ListItem] = []
    seen: set[Any] = set()
    for node in _issue_nodes(page):
        number = node.get("number")
        if not number or number in seen:
            continue
        seen.add(number)
        url = f"https://github.com/{repo}/issues/{number}"
        author = node.get("author") if isinstance(node.get("author"), dict) else {}
        items.append(
            ListItem(
                id=str(number),
                # titleHtml 去 HTML 标签并反转义
                title=html.unescape(re.sub(r"<[^>]+>", "", node.get("titleHtml") or "")).strip(),
                url=url,
                mobileUrl=url,
                author=author.get("login"),
                # createdAt 是 ISO UTC → 毫秒
                timestamp=get_time(node.get("createdAt")),
            )
        )
    return items


def _issue_nodes(page: str) -> list[dict[str, Any]]:
    matched = _EMBEDDED.search(page)
    if not matched:
        raise RuntimeError("github issues page has no react-app.embeddedData (page changed)")
    try:
        payload = json.loads(matched.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"github issues embedded JSON is not valid: {exc}") from exc
    queries = payload.get("payload", {}).get("preloadedQueries") or []
    search = (
        (((queries[0].get("result") or {}).get("data") or {}).get("repository") or {}).get("search")
        if queries
        else None
    )
    if not isinstance(search, dict):
        # 上游结构漂移是路由级错误,不是调用方传参错误
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "github issues embedded JSON has no repository.search (page changed)"
        )
    return [
        edge["node"]
        for edge in search.get("edges") or []
        if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
    ]
