from __future__ import annotations

import re
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "yahoo"

type_map: dict[str, str] = {
    "yahoo-100": "Yahoo 100",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Yahoo",
    "description": "Yahoo 100 实时话题榜",
    "params": {
        "type": {
            "name": "榜单类型",
            "type": type_map,
        },
    },
    "link": "https://www.yahoo.com/trending/",
}

_API_URL = "https://nexus-gateway-prod.media.yahoo.com"
_SOURCE_URL = "https://www.yahoo.com/trending/"
_MAX_ITEMS = 100
_PAGE_LIMIT = 100
_MAX_PAGES = 4
_VALID_CATEGORIES = {
    "Business",
    "Entertainment",
    "Health",
    "Lifestyle",
    "News",
    "Sports",
    "Technology",
}
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_QUERY = """
query GetY100Topics($limit: Int!, $nextToken: String) {
  listY100Topics(limit: $limit, nextToken: $nextToken) {
    nextToken
    items {
      id
      rank
      categoryGroup
      overrideCategoryGroup
      topicLabel
      overrideLabel
      longLabel
      overrideLongLabel
      topicDescription
      overrideDescription
      badges
      topHashtag
      topHashtagUrl
      topPlatform
    }
  }
}
""".strip()


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "yahoo-100")
    selected = requested if requested in type_map else "yahoo-100"
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    pages: list[object] = []
    next_token: str | None = None
    from_cache = True
    update_times: list[str] = []

    for _ in range(_MAX_PAGES):
        result = await post(
            url=_API_URL,
            body={
                "operationName": "GetY100Topics",
                "query": _QUERY,
                "variables": {
                    "limit": _PAGE_LIMIT,
                    "nextToken": next_token,
                },
            },
            no_cache=no_cache,
            ttl=600,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": _SOURCE_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36 "
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "x-yahoo-cg-client-name": "news",
                "y-rid": "whats-hot-yahoo-100",
            },
        )
        page = _page_contract(result.data)
        if page is None:
            return {
                "from_cache": result.from_cache,
                "update_time": result.update_time,
                "data": [],
            }
        rows, new_token = page
        pages.extend(rows)
        from_cache = from_cache and result.from_cache
        update_times.append(result.update_time)
        if any(_integer(row.get("rank")) == _MAX_ITEMS for row in rows):
            break
        if not new_token or new_token == next_token:
            break
        next_token = new_token

    return {
        "from_cache": from_cache,
        "update_time": max(update_times),
        "data": _parse_topics(pages),
    }


def _page_contract(payload: object) -> tuple[list[dict], str | None] | None:
    if not isinstance(payload, dict) or payload.get("errors"):
        return None
    data = payload.get("data")
    listing = data.get("listY100Topics") if isinstance(data, dict) else None
    rows = listing.get("items") if isinstance(listing, dict) else None
    token = listing.get("nextToken") if isinstance(listing, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    if token is not None and (not isinstance(token, str) or not token.strip()):
        return None
    if not all(isinstance(row, dict) for row in rows):
        return None
    return rows, token


def _parse_topics(rows: list[object]) -> list[ListItem]:
    selected: dict[int, dict] = {}
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            return []
        rank = _integer(row.get("rank"))
        if rank is None or rank < 1:
            return []
        if rank > _MAX_ITEMS:
            continue
        topic_id = _text(row.get("id"))
        title = _text(row.get("overrideLabel")) or _text(row.get("topicLabel"))
        category = _text(row.get("overrideCategoryGroup")) or _text(
            row.get("categoryGroup")
        )
        description = _text(row.get("overrideDescription")) or _text(
            row.get("topicDescription")
        )
        long_label = _text(row.get("overrideLongLabel")) or _text(
            row.get("longLabel")
        )
        title_key = _identity(title)
        if (
            _UUID_RE.fullmatch(topic_id) is None
            or not title
            or not description
            or category not in _VALID_CATEGORIES
            or rank in selected
            or topic_id in seen_ids
            or title_key in seen_titles
        ):
            return []
        selected[rank] = row
        seen_ids.add(topic_id)
        seen_titles.add(title_key)

    if sorted(selected) != list(range(1, _MAX_ITEMS + 1)):
        return []

    items: list[ListItem] = []
    for rank in range(1, _MAX_ITEMS + 1):
        row = selected[rank]
        topic_id = _text(row.get("id"))
        title = _text(row.get("overrideLabel")) or _text(row.get("topicLabel"))
        category = _text(row.get("overrideCategoryGroup")) or _text(
            row.get("categoryGroup")
        )
        description = _text(row.get("overrideDescription")) or _text(
            row.get("topicDescription")
        )
        long_label = _text(row.get("overrideLongLabel")) or _text(
            row.get("longLabel")
        )
        badges = row.get("badges")
        badge_text = [
            _text(value)
            for value in badges
            if isinstance(value, str) and _text(value)
        ] if isinstance(badges, list) else []
        hashtag = _text(row.get("topHashtag"))
        parts = [value for value in [long_label if long_label != title else "", description] if value]
        if badge_text:
            parts.append("标记：" + "、".join(badge_text))
        if hashtag:
            parts.append(f"热门标签：#{hashtag}")
        url = f"{_SOURCE_URL}#{topic_id}"
        items.append(
            ListItem(
                id=topic_id,
                title=title,
                author=category,
                desc=" · ".join(parts),
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _identity(value: str) -> str:
    return re.sub(r"[^\w]+", "", value.casefold())


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
