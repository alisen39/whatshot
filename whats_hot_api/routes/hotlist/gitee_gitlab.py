"""Gitee 与 GitLab 项目榜(单子榜)。

whatshot 此前没有 GitLab / Gitee 路由。唯一能做的子榜是 GitLab 探索页"Most starred"
(按星标数倒序的公开项目),取同一份数据的官方 REST API:

    GET https://gitlab.com/api/v4/projects?order_by=star_count&sort=desc&per_page=20&simple=true&active=true

- 公开接口,不需要 token;per_page=20 与探索页一页 20 个相同
- active=true 与页面"Active"标签口径一致(排除已归档、待删除项目;推翻性验证结论)
- order_by 必需:去掉后缺省按 created_at 排,结果与星标榜 0 重合;order_by=trending 返回 400
- 未认证 API 限流 500 次/分钟(响应头 RateLimit-Limit),429 由 HTTP 层直接报错
- Gitee 今日/本周热门入口返回 JS 挑战 + 滑块验证码,GitLab Trending 已下线,均不做(见 board_api README)

title 取 name_with_namespace("组 / 项目",探索页显示口径;tophub 只显示 name)。
id 用项目 id;timestamp 用 created_at(ISO,毫秒化)。UA/Accept 均非必需
(python-httpx 缺省请求头也 200),这里按 JSON 口径带 Accept。
"""

from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "gitee-gitlab"

type_map: dict[str, str] = {
    "gitlab-most-stars": "GitLab · Most starred",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Gitee 与 GitLab",
    "description": "GitLab 探索页按星标数排序的公开项目(官方 REST API);Gitee 热门榜因反爬不做。",
    "link": "https://gitlab.com/explore/projects/active?sort=stars_desc",
    "params": {
        "type": {
            "name": "站点-栏目",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = next(iter(type_map))

_API = "https://gitlab.com/api/v4/projects"
_QUERY = {
    "order_by": "star_count",
    "sort": "desc",
    "per_page": 20,
    "simple": "true",
    "active": "true",
}
_HEADERS = {"Accept": "application/json"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    result = await get(url=_API, params=_QUERY, headers=_HEADERS, no_cache=no_cache)
    items = _project_items(result.data)
    if not items:
        raise RuntimeError("GitLab projects API returned no projects")
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _project_items(rows: object) -> list[ListItem]:
    if not isinstance(rows, list):
        # 上游结构漂移是路由级错误,不是调用方传参错误
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"GitLab projects API response is not a list: {str(rows)[:200]}"
        )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None or not row.get("web_url"):
            continue
        url = str(row["web_url"])
        namespace = row.get("namespace") if isinstance(row.get("namespace"), dict) else {}
        items.append(
            ListItem(
                id=str(row["id"]),
                # 探索页显示"组 / 项目";没有 name_with_namespace 时退回路径或名称
                title=_text(row.get("name_with_namespace") or row.get("path_with_namespace") or row.get("name")),
                url=url,
                mobileUrl=url,
                desc=_text(row.get("description")) or None,
                hot=row.get("star_count"),
                author=namespace.get("name"),
                cover=_avatar(row.get("avatar_url")),
                # created_at 是 ISO UTC,由 get_time 统一为毫秒
                timestamp=get_time(str(row.get("created_at") or "")) or None,
            )
        )
    return items


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _avatar(value: object) -> str | None:
    """项目头像;没设头像为 null,部分项目给相对路径,统一补成绝对地址。"""
    if not isinstance(value, str) or not value.strip():
        return None
    avatar = value.strip()
    if avatar.startswith(("http://", "https://")):
        return avatar
    return f"https://gitlab.com{avatar}"
