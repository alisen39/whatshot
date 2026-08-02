from __future__ import annotations

from html import unescape

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "stackoverflow"

type_map: dict[str, str] = {
    "hot": "热门问题",
    "unanswered": "高票未解决",
    "featured": "悬赏问题",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Stack Overflow",
    "description": "Stack Overflow 热门、未解决与悬赏问题",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://stackoverflow.com/questions",
}

_API_BASE = "https://api.stackexchange.com/2.3/questions"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    selected_type = type_param if type_param in type_map else "hot"
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
    path = {
        "hot": "",
        "unanswered": "/unanswered",
        "featured": "/featured",
    }[board_type]
    sort = {"hot": "hot", "unanswered": "votes", "featured": "activity"}[
        board_type
    ]
    url = f"{_API_BASE}{path}"
    params = {
        "order": "desc",
        "sort": sort,
        "site": "stackoverflow",
        "pagesize": "50",
    }
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params=params,
        cache_key=f"{url}?order=desc&sort={sort}&site=stackoverflow&pagesize=50",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
    )
    data = [_question_item(row, board_type) for row in (result.data or {}).get("items", [])]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _question_item(row: dict, board_type: str) -> ListItem | None:
    question_id = str(row.get("question_id") or "").strip()
    title = unescape(str(row.get("title") or "")).strip()
    url = str(row.get("link") or "").strip()
    if not question_id or not title or not url:
        return None
    owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
    tags = [unescape(str(tag)).strip() for tag in row.get("tags", []) if str(tag).strip()]
    desc_parts = []
    if board_type == "featured" and row.get("bounty_amount") is not None:
        desc_parts.append(f"悬赏：{row['bounty_amount']}")
    if row.get("answer_count") is not None:
        desc_parts.append(f"回答：{row['answer_count']}")
    if row.get("view_count") is not None:
        desc_parts.append(f"浏览：{row['view_count']}")
    if tags:
        desc_parts.append("标签：" + "、".join(tags[:6]))
    return ListItem(
        id=question_id,
        title=title,
        author=unescape(str(owner.get("display_name") or "")).strip() or None,
        desc=" · ".join(desc_parts) or None,
        hot=row.get("score"),
        timestamp=get_time(row.get("creation_date")),
        url=url,
        mobileUrl=url,
    )
