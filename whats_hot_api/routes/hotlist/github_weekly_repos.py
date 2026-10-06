"""GitHub 周刊仓库(3 个子榜:Releases)。

与既有 GitHub 路由的边界:github 路由取 GitHub 官方 Blog 与 tophub 风格的仓库热榜,
github-trending-lang 取 /trending 页;本路由取"按期发布"的周刊仓库的 Releases 列表,
来源不重叠。子榜与仓库的对应关系照 board_api 证据
(tophub 节点条目链接指向哪个仓库就取哪个仓库):

- d2-daily      -> d2-projects/d2-daily 的 Releases(已停更,最后一期 2019-09-03 第 170 期,
                   tophub 同样停在该期;照原站当前列表输出)
- fe-weekly     -> ascoders/weekly 的 Releases(缺省榜)
- ios-weekly    -> SwiftOldDriver/iOS-Weekly 的 Releases

hackernews-weekly(headllines/hackernews-weekly 的 Issues)已因上游不可达下线。

取数不调 GitHub REST API(避免未登录每小时 60 次限制):Releases 用官方 Atom feed
releases.atom(固定最近 10 条),解析与 claude-code-releases 路由相同。

反爬:无。UA / cookie 均不校验(实测 curl 缺省 UA 响应逐字节相同),仍按站点惯例带浏览器 UA。
id 用上游稳定标识(Atom entry id,禁名次);timestamp 统一毫秒。
"""

from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "github-weekly-repos"

# 子榜键 -> (榜名, 仓库)。fe-weekly 是 board_api 的缺省榜,声明序第一个即默认榜
_BOARDS: dict[str, tuple[str, str]] = {
    "fe-weekly": ("前端精读周刊", "ascoders/weekly"),
    "d2-daily": ("D2-daily", "d2-projects/d2-daily"),
    "ios-weekly": ("老司机 iOS 周报", "SwiftOldDriver/iOS-Weekly"),
}

type_map: dict[str, str] = {key: label for key, (label, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "GitHub 周刊仓库",
    "description": "GitHub 上按期发布的周刊 / 日刊仓库:D2-daily、前端精读周刊、老司机 iOS 周报。",
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


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, repo = _BOARDS[type_param]
    list_data = await _get_list(repo, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": list_data["link"]},
        type=f"{label} · Releases",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(repo: str, no_cache: bool) -> dict:
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
    if not items:
        raise RuntimeError(f"{repo} releases returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "link": f"https://github.com/{repo}/releases",
    }
