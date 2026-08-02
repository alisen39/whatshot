from __future__ import annotations

import re
from urllib.parse import urlparse

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "xiaoe"

SOURCE_LINK = "https://sem.xiaoe-tech.com/moreNews"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "小鹅通",
    "description": "小鹅通官方增长、运营、产品与行业实践文章",
    "link": SOURCE_LINK,
}

_API_URL = "https://sem.xiaoe-tech.com/extendRead_v2/1.0.0"
_ARTICLE_URL = "https://sem.xiaoe-tech.com/moreNews/articleDetail-{item_id}.html"
_TIME_RE = re.compile(r"^20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="增长干货",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        response_type="json",
        params={
            "page": 1,
            "page_size": _MAX_ITEMS,
            "search_type": 1,
            "pinyin": "",
        },
        cache_key=f"xiaoe:more-news:latest:{_MAX_ITEMS}",
        headers={
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_response(result.data),
    }


def _parse_response(payload: object) -> list[ListItem]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return []
    result = payload.get("data")
    if not isinstance(result, dict):
        return []
    rows = result.get("list")
    pagination = result.get("pagination")
    if not isinstance(rows, list) or not rows or not isinstance(pagination, dict):
        return []
    try:
        current_page = int(pagination.get("current_page"))
        page_size = int(pagination.get("page_size"))
        total = int(pagination.get("total"))
        total_pages = int(pagination.get("total_pages"))
    except (TypeError, ValueError):
        return []
    expected_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    if (
        current_page != 1
        or page_size != _MAX_ITEMS
        or total < len(rows)
        or len(rows) > _MAX_ITEMS
        or total_pages != expected_pages
    ):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    previous_timestamp: int | None = None
    for row in rows:
        if not isinstance(row, dict):
            return []
        item_id = str(row.get("id") or "").strip()
        title = _clean_text(row.get("title"))
        title_key = _identity_text(title)
        published_at = _clean_text(row.get("time"))
        expected_path = f"/moreNews/articleDetail-{item_id}.html"
        cover_value = _clean_text(row.get("img_url"))
        cover = _https_url(cover_value)
        timestamp = get_time(published_at) if _TIME_RE.fullmatch(published_at) else None
        if (
            not item_id.isdigit()
            or int(item_id) <= 0
            or not title_key
            or not timestamp
            or row.get("news_link") != expected_path
            or (cover_value and cover is None)
            or item_id in seen_ids
            or title_key in seen_titles
            or (previous_timestamp is not None and timestamp > previous_timestamp)
        ):
            return []
        seen_ids.add(item_id)
        seen_titles.add(title_key)
        previous_timestamp = timestamp
        url = _ARTICLE_URL.format(item_id=item_id)
        data.append(
            ListItem(
                id=item_id,
                title=title,
                author="小鹅通",
                desc=_clean_text(row.get("summary"))[:240] or None,
                cover=cover,
                timestamp=timestamp,
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _https_url(value: object) -> str | None:
    url = _clean_text(value)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return url


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _identity_text(value: object) -> str:
    return re.sub(r"[^\w]+", " ", _clean_text(value).casefold()).strip()
