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


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", "models")
    if selected not in type_map:
        selected = "models"
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
