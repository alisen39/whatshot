from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "v2ex"

type_map: dict[str, str] = {
    "hot": "最热主题",
    "latest": "最新主题",
    "share": "分享主题",
    "nodes": "主题最多节点",
}

ROUTE_META: dict = {
    "name": "v2ex",
    "title": "V2EX",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.v2ex.com/",
}

_NODES_URL = "https://www.v2ex.com/api/nodes/all.json"
_NODE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_MAX_NODE_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    selected_type = type_param if type_param in type_map else "hot"
    if selected_type == "share":
        list_data = await _get_share_list(no_cache)
    elif selected_type == "nodes":
        list_data = await _get_nodes_list(no_cache)
    else:
        list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://www.v2ex.com/api/topics/{type_param}.json"
    result = await get(url, no_cache=no_cache)
    items = result.data
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["id"],
                title=v["title"],
                desc=v.get("content"),
                author=v.get("member", {}).get("username"),
                timestamp=get_time(v.get("created")),
                hot=v.get("replies"),
                url=v.get("url", ""),
                mobileUrl=v.get("url", ""),
            )
            for v in items
        ],
    }


async def _get_share_list(no_cache: bool) -> dict:
    feed_names = ("create", "ideas", "programmer", "share")
    results = []
    for feed_name in feed_names:
        result = await get(
            url=f"https://www.v2ex.com/feed/{feed_name}.json",
            no_cache=no_cache,
        )
        results.append(result)

    data: list[ListItem] = []
    seen: set[str] = set()
    for result in results:
        payload = result.data if isinstance(result.data, dict) else {}
        for item in payload.get("items") or []:
            item_url = str(item.get("url") or "").strip()
            item_id = str(item.get("id") or item_url).strip()
            title = str(item.get("title") or "").strip()
            dedupe_key = item_id or item_url
            if not title or not item_url or not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            authors = item.get("authors") or []
            author = None
            if authors and isinstance(authors[0], dict):
                author = authors[0].get("name")
            data.append(
                ListItem(
                    id=item_id,
                    title=title,
                    desc=(item.get("summary") or item.get("content_text") or None),
                    author=author,
                    timestamp=get_time(
                        item.get("date_modified") or item.get("date_published")
                    ),
                    url=item_url,
                    mobileUrl=item_url,
                )
            )

    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    update_times = [result.update_time for result in results if result.update_time]
    return {
        "from_cache": all(result.from_cache for result in results),
        "update_time": max(update_times) if update_times else "",
        "data": data,
    }


async def _get_nodes_list(no_cache: bool) -> dict:
    result = await get(
        url=_NODES_URL,
        no_cache=no_cache,
        cache_key="v2ex:nodes:topics",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_nodes(result.data),
    }


def _parse_nodes(payload: object) -> list[ListItem]:
    if not isinstance(payload, list):
        return []
    data: list[ListItem] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    seen_urls: set[str] = set()
    for value in payload:
        if not isinstance(value, dict):
            continue
        node_id = _nonnegative_int(value.get("id"))
        topics = _nonnegative_int(value.get("topics"))
        stars = _nonnegative_int(value.get("stars"))
        name = _clean_text(value.get("name"))
        title = _clean_text(value.get("title"))
        url = _clean_text(value.get("url"))
        if (
            node_id is None
            or node_id <= 0
            or topics is None
            or stars is None
            or not _NODE_NAME_RE.fullmatch(name)
            or not title
            or url != f"https://www.v2ex.com/go/{name}"
        ):
            continue
        if node_id in seen_ids or name in seen_names or url in seen_urls:
            return []
        seen_ids.add(node_id)
        seen_names.add(name)
        seen_urls.add(url)
        data.append(
            ListItem(
                id=node_id,
                title=f"{title}（{name}）",
                desc=f"累计主题：{topics} · 收藏：{stars}",
                hot=topics,
                url=url,
                mobileUrl=url,
            )
        )

    data.sort(key=lambda item: item.hot or 0, reverse=True)
    return data[:_MAX_NODE_ITEMS]


def _nonnegative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
