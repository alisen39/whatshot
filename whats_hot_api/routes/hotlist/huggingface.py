from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "huggingface"
_BASE = "https://huggingface.co/api"

type_map: dict[str, str] = {
    "models": "热门模型",
    "datasets": "热门数据集",
    "spaces": "热门 Spaces",
    "trending-models": "Trending 模型",
    "likes-models": "Most Likes 模型",
    "trending-datasets": "Trending 数据集",
    "likes-datasets": "Most Likes 数据集",
    "trending-spaces": "Trending Spaces",
    "blog-zh": "中文博客",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Hugging Face",
    "description": "Hugging Face 公开模型、数据集与 Spaces 榜单",
    "params": {"type": {"name": "榜单分类", "type": type_map}},
    "link": "https://huggingface.co/",
}

_BOARD_CONFIG = {
    "models": ("models", "downloads", "models"),
    "datasets": ("datasets", "downloads", "datasets"),
    "spaces": ("spaces", "likes", "spaces"),
}

# board_api 验证过的扩展排序榜:(endpoint, sort, path_prefix, hot 取值字段, spaces 展示风格)。
# 页面 "Trending" 对应接口参数 sort=trendingScore(sort=trending 返回 400);
# trendingScore 只在 expand[] 序列化里,所以扩展榜用 expand[] 而不是 full=true。
# Spaces 展示风格:标题用 README 的 title(cardData.title),desc 用 short_description,没有时退标签;
# 既有 spaces 榜保持原行为(标题用仓库 id),不做兼容性变更。
_EXTRA_BOARDS = {
    "trending-models": ("models", "trendingScore", "models", "trendingScore", False),
    "likes-models": ("models", "likes", "models", "likes", False),
    "trending-datasets": ("datasets", "trendingScore", "datasets", "trendingScore", False),
    "likes-datasets": ("datasets", "likes", "datasets", "likes", False),
    "trending-spaces": ("spaces", "trendingScore", "spaces", "trendingScore", True),
}
_EXPAND = ("author", "likes", "trendingScore", "lastModified", "tags")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", "models")
    if selected not in type_map:
        selected = "models"
    if selected == "blog-zh":
        rows = await _get_blog_zh(no_cache)
    elif selected in _EXTRA_BOARDS:
        rows = await _get_extra_board(selected, no_cache)
    else:
        rows = await _get_board(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(rows["data"]),
        fromCache=rows["from_cache"],
        updateTime=rows["update_time"],
        data=rows["data"],
    )


async def _get_board(board: str, no_cache: bool) -> dict:
    endpoint, sort, path_prefix = _BOARD_CONFIG[board]
    url = f"{_BASE}/{endpoint}"
    result = await get(
        url=url,
        params={"sort": sort, "direction": "-1", "limit": "50", "full": "true"},
        no_cache=no_cache,
        response_type="json",
        cache_key=f"huggingface:{board}:{sort}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    raw = result.data if isinstance(result.data, list) else []
    data: list[ListItem] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id") or row.get("_id") or "").strip()
        title = item_id
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        author = str(row.get("author") or (item_id.split("/", 1)[0] if "/" in item_id else "")).strip() or None
        tags = row.get("tags")
        tag_text = ", ".join(str(tag) for tag in tags[:10] if not str(tag).startswith("license:")) if isinstance(tags, list) else ""
        is_space = board == "spaces"
        hot_value = row.get("likes") if is_space else row.get("downloads")
        url_path = f"{path_prefix}/{item_id}" if path_prefix != "models" else item_id
        item_url = f"https://huggingface.co/{url_path}"
        data.append(
            ListItem(
                id=item_id,
                title=title,
                author=author,
                hot=hot_value,
                desc=tag_text or None,
                timestamp=get_time(row.get("lastModified")),
                url=item_url,
                mobileUrl=item_url,
            )
        )
        if len(data) >= 50:
            break
    if not data:
        raise ValueError(f"Hugging Face {board} board returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _get_extra_board(board: str, no_cache: bool) -> dict:
    endpoint, sort, path_prefix, hot_field, spaces_style = _EXTRA_BOARDS[board]
    expand = [*_EXPAND, "cardData"] if spaces_style else list(_EXPAND)
    result = await get(
        url=f"{_BASE}/{endpoint}",
        params=[("sort", sort), ("limit", "50"), *(("expand[]", field) for field in expand)],
        no_cache=no_cache,
        response_type="json",
        cache_key=f"huggingface:{board}:{sort}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    raw = result.data if isinstance(result.data, list) else []
    data: list[ListItem] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        card = row.get("cardData") if isinstance(row.get("cardData"), dict) else {}
        title = str(card.get("title") or "").strip() or item_id
        desc = (
            str(card.get("short_description") or "").strip()
            or ", ".join(str(tag) for tag in (row.get("tags") or [])[:10] if not str(tag).startswith("license:"))
            or None
        )
        author = str(row.get("author") or (item_id.split("/", 1)[0] if "/" in item_id else "")).strip() or None
        url_path = f"{path_prefix}/{item_id}" if path_prefix != "models" else item_id
        item_url = f"https://huggingface.co/{url_path}"
        data.append(
            ListItem(
                id=item_id,
                title=title,
                author=author,
                hot=row.get(hot_field),
                desc=desc,
                timestamp=get_time(row.get("lastModified")),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    if not data:
        raise ValueError(f"Hugging Face {board} board returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _get_blog_zh(no_cache: bool) -> dict:
    # /blog/zh 页面的数据接口;中文博客没有 RSS(/blog/zh/feed.xml 404),英文 feed 不含中文文章。
    # allBlogs 是博客列表;communityBlogPosts 是侧栏社区文章,不属于中文博客。
    result = await get(
        url=f"{_BASE}/blog/zh",
        no_cache=no_cache,
        response_type="json",
        cache_key="huggingface:blog-zh",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    posts = (result.data or {}).get("allBlogs") or []
    data: list[ListItem] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        path = post.get("url")
        url = path if isinstance(path, str) and path.startswith(("http://", "https://")) else (
            f"https://huggingface.co{path}" if isinstance(path, str) and path else ""
        )
        title = str(post.get("title") or "").strip()
        if not url or not title:
            continue
        authors = [
            str(a.get("fullname") or a.get("name") or "").strip()
            for a in post.get("authorsData") or []
            if isinstance(a, dict) and str(a.get("fullname") or a.get("name") or "").strip()
        ]
        author = (", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")) or None
        thumb = post.get("thumbnail")
        cover = thumb if isinstance(thumb, str) and thumb.startswith(("http://", "https://")) else (
            f"https://huggingface.co{thumb}" if isinstance(thumb, str) and thumb else None
        )
        data.append(
            ListItem(
                id=url,
                title=title,
                url=url,
                mobileUrl=url,
                author=author,
                cover=cover,
                hot=post.get("upvotes"),
                timestamp=get_time(post.get("publishedAt")),
            )
        )
    if not data:
        raise ValueError("Hugging Face blog-zh board returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
