from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "devto"

type_map: dict[str, str] = {
    "feed": "精选 RSS",
    "top": "今日热门",
    "latest": "最新发布",
}

ROUTE_META = {"name": ROUTE_NAME, "title": "DEV.to", "description": "Developer community posts, tutorials, and career stories.", "link": "https://dev.to/", "params": {"type": {"name": "榜单分类", "type": type_map}}}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "feed")
    selected_type = type_param if type_param in type_map else "feed"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    if board_type == "feed":
        result = await get(url="https://dev.to/feed", no_cache=no_cache, response_type="text", headers={"Accept": "application/rss+xml,application/xml,text/xml", "User-Agent": "Mozilla/5.0"})
        return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)}
    if board_type == "top":
        url = "https://dev.to/api/articles"
        params = {"top": "1", "per_page": "50"}
    else:
        url = "https://dev.to/api/articles/latest"
        params = {"per_page": "50", "page": "1"}
    result = await get(
        url=url,
        params=params,
        no_cache=no_cache,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    items = [_article_item(row) for row in result.data or []]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in items if item is not None],
    }


def _article_item(row: dict) -> ListItem | None:
    item_id = row.get("id")
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if item_id is None or not title or not url:
        return None
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    tags = row.get("tag_list") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    description = str(row.get("description") or "").strip()
    meta = []
    if tags:
        meta.append("标签：" + "、".join(str(tag) for tag in tags))
    if row.get("comments_count") is not None:
        meta.append(f"评论：{row['comments_count']}")
    if row.get("reading_time_minutes") is not None:
        meta.append(f"阅读：{row['reading_time_minutes']} 分钟")
    desc = " · ".join([part for part in [description, *meta] if part]) or None
    return ListItem(
        id=str(item_id),
        title=title,
        author=user.get("username") or user.get("name"),
        desc=desc,
        cover=row.get("cover_image") or row.get("social_image"),
        hot=row.get("public_reactions_count"),
        timestamp=get_time(row.get("published_at")),
        url=url,
        mobileUrl=url,
    )


handle_route.__module__ = __name__
