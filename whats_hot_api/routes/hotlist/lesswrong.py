from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "lesswrong"

type_map: dict[str, str] = {
    "frontpage": "算法首页",
    "curated": "编辑精选",
    "new": "最新发布",
    "shortform": "短内容",
    "top-week": "本周高分",
    "top-month": "本月高分",
    "top-year": "本年高分",
    "top-all": "历史高分",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "LessWrong",
    "description": "LessWrong 理性、人工智能与决策讨论",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.lesswrong.com/",
}

_GRAPHQL_URL = "https://www.lesswrong.com/graphql"
_TOP_PERIOD_DAYS = {"top-week": 7, "top-month": 30, "top-year": 365}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "frontpage")
    selected_type = type_param if type_param in type_map else "frontpage"
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
    query = _posts_query(board_type)
    result = await post(
        url=_GRAPHQL_URL,
        body={"query": query},
        no_cache=no_cache,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.lesswrong.com/",
        },
    )
    rows = (((result.data or {}).get("data") or {}).get("posts") or {}).get(
        "results", []
    )
    data = [_post_item(row) for row in rows]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _posts_query(board_type: str) -> str:
    view = board_type if board_type in {"frontpage", "curated", "new", "shortform"} else "top"
    after = ""
    if board_type in _TOP_PERIOD_DAYS:
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=_TOP_PERIOD_DAYS[board_type])
        after = f', after: "{cutoff.isoformat()}"'
    return f'''query PostsList {{
      posts(input: {{terms: {{view: "{view}"{after}, limit: 50}}}}) {{
        results {{
          _id title user {{ displayName }} baseScore commentCount slug postedAt
          tags {{ name }}
        }}
      }}
    }}'''


def _post_item(row: dict) -> ListItem | None:
    post_id = str(row.get("_id") or "").strip()
    title = str(row.get("title") or "").strip()
    slug = str(row.get("slug") or "").strip()
    if not post_id or not title:
        return None
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    tags = [
        str(tag.get("name") or "").strip()
        for tag in row.get("tags", [])
        if isinstance(tag, dict) and str(tag.get("name") or "").strip()
    ]
    url = f"https://www.lesswrong.com/posts/{post_id}/{slug}".rstrip("/")
    desc_parts = []
    if row.get("commentCount") is not None:
        desc_parts.append(f"评论：{row['commentCount']}")
    if tags:
        desc_parts.append("标签：" + "、".join(tags[:6]))
    return ListItem(
        id=post_id,
        title=title,
        author=user.get("displayName"),
        desc=" · ".join(desc_parts) or None,
        hot=row.get("baseScore"),
        timestamp=get_time(row.get("postedAt")),
        url=url,
        mobileUrl=url,
    )
