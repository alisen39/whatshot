from __future__ import annotations

from datetime import datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "oeis"

type_map: dict[str, str] = {
    "recent": "近期新增",
    "best": "精选数列",
    "more": "待补充数列",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OEIS",
    "description": "整数数列在线大全的近期新增、精选与待补充数列",
    "params": {
        "type": {
            "name": "数列分类",
            "type": type_map,
        },
    },
    "link": "https://oeis.org/",
}

_BASE_URL = "https://oeis.org"
_SEARCH_URL = f"{_BASE_URL}/search"
_BOARD_QUERIES: dict[str, tuple[str, str]] = {
    "recent": ("keyword:new", "created"),
    "best": ("keyword:nice", "relevance"),
    "more": ("keyword:more", "relevance"),
}
_MAX_ITEMS = 10
_PREVIEW_TERMS = 12


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "recent")
    selected = requested if requested in type_map else "recent"
    list_data = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    query, sort = _BOARD_QUERIES[board_type]
    params = {
        "q": query,
        "fmt": "json",
        "start": "0",
        "sort": sort,
    }
    result = await get(
        url=_SEARCH_URL,
        params=params,
        no_cache=no_cache,
        response_type="json",
        cache_key=(
            f"{_SEARCH_URL}?q={query}&fmt=json&start=0&sort={sort}"
        ),
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    data = _parse_sequences(result.data or [], board_type)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_sequences(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, list):
        return []
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in payload[:_MAX_ITEMS]:
        item = _sequence_item(row, board_type, len(data) + 1)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
    return data


def _sequence_item(
    row: object,
    board_type: str,
    rank: int,
) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    number = _integer(row.get("number"))
    name = _text(row.get("name"))
    if number is None or number < 0 or not name:
        return None

    sequence_id = f"A{number:06d}"
    preview = _preview(row.get("data"))
    keywords = [
        value.strip()
        for value in _text(row.get("keyword")).split(",")
        if value.strip()
    ]
    revision = _integer(row.get("revision"))
    rank_label = {
        "recent": "近期新增顺序",
        "best": "精选检索顺序",
        "more": "待补充检索顺序",
    }[board_type]
    desc_parts = [f"{rank_label}：{rank}", f"编号：{sequence_id}"]
    if preview:
        desc_parts.append(f"数列：{preview}")
    if keywords:
        desc_parts.append(f"关键词：{', '.join(keywords)}")
    if revision is not None:
        desc_parts.append(f"修订版本：{revision}")

    url = f"{_BASE_URL}/{sequence_id}"
    return ListItem(
        id=sequence_id,
        title=name,
        author=_text(row.get("author")) or None,
        desc=" · ".join(desc_parts),
        timestamp=_timestamp_seconds(row.get("created")),
        url=url,
        mobileUrl=url,
    )


def _preview(value: object) -> str:
    terms = [
        term.strip()
        for term in _text(value).split(",")
        if term.strip()
    ]
    if not terms:
        return ""
    visible = terms[:_PREVIEW_TERMS]
    suffix = (
        f", …（另有 {len(terms) - _PREVIEW_TERMS} 项）"
        if len(terms) > _PREVIEW_TERMS
        else ""
    )
    return ", ".join(visible) + suffix


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_seconds(value: object) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None
