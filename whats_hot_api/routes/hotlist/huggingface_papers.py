from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "huggingface-papers"

type_map: dict[str, str] = {
    "daily": "Daily Papers",
    "papers": "Daily Papers",
    "weekly": "Weekly 热门",
}

_PERIOD_BY_TYPE: dict[str, str] = {
    "daily": "day",
    "papers": "day",
    "weekly": "weekly",
}

ROUTE_META = {"name": ROUTE_NAME, "title": "Hugging Face · Daily Papers", "description": "Daily machine learning papers highlighted by Hugging Face.", "link": "https://huggingface.co/papers", "params": {"type": {"name": "榜单分类", "type": type_map}}}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "daily")
    selected_type = type_param if type_param in type_map else "daily"
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
    result = await get(
        url="https://huggingface.co/api/papers",
        params={"period": _PERIOD_BY_TYPE[board_type]},
        no_cache=no_cache,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    rows = sorted(
        result.data if isinstance(result.data, list) else [],
        key=lambda row: row.get("upvotes") or 0,
        reverse=True,
    )
    data = [_paper_item(row) for row in rows[:50]]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _paper_item(row: dict) -> ListItem | None:
    paper_id = str(row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    if not paper_id or not title:
        return None
    authors = [
        str(author.get("name") or "").strip()
        for author in row.get("authors", [])
        if isinstance(author, dict) and str(author.get("name") or "").strip()
    ]
    url = f"https://huggingface.co/papers/{paper_id}"
    return ListItem(
        id=paper_id,
        title=title,
        author=", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "") or None,
        desc=str(row.get("summary") or "").strip() or None,
        cover=row.get("thumbnailUrl"),
        hot=row.get("upvotes"),
        timestamp=get_time(row.get("publishedAt")),
        url=url,
        mobileUrl=url,
    )


handle_route.__module__ = __name__
