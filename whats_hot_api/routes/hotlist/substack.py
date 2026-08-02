from __future__ import annotations

from urllib.parse import urlparse

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "substack"

type_map: dict[str, str] = {
    "technology": "科技上升榜",
    "business": "商业上升榜",
    "culture": "文化上升榜",
    "us-politics": "美国政治上升榜",
    "science": "科学上升榜",
    "health": "健康上升榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Substack",
    "description": "Substack 官方分类中的上升 Newsletter 与播客",
    "params": {
        "type": {
            "name": "分类",
            "type": type_map,
        },
    },
    "link": "https://substack.com/explore",
}

_CATEGORY_IDS = {
    "technology": 4,
    "business": 62,
    "culture": 96,
    "us-politics": 76739,
    "science": 134,
    "health": 355,
}
_API_URL = "https://substack.com/api/v1/search/explore/web"
_MAX_ITEMS = 5


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "technology")
    selected_type = type_param if type_param in type_map else "technology"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(category: str, no_cache: bool) -> dict:
    category_id = _CATEGORY_IDS[category]
    result = await get(
        url=f"{_API_URL}?tab={category_id}&type=category",
        no_cache=no_cache,
        cache_key=f"substack:rising:{category}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_leaderboard(result.data, category),
    }


def _parse_leaderboard(payload: object, category: str) -> list[ListItem]:
    if not isinstance(payload, dict) or category not in _CATEGORY_IDS:
        return []
    tracking = payload.get("trackingParameters")
    if (
        not isinstance(tracking, dict)
        or str(tracking.get("tab_id")) != str(_CATEGORY_IDS[category])
    ):
        return []
    modules = payload.get("items")
    if not isinstance(modules, list):
        return []

    matching_modules = [
        module
        for module in modules
        if _is_expected_leaderboard(module, category)
    ]
    if len(matching_modules) != 1:
        return []

    rows = matching_modules[0].get("items")
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        publication = _publication_from_row(row)
        item = _publication_item(publication)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _is_expected_leaderboard(module: object, category: str) -> bool:
    if not isinstance(module, dict) or module.get("type") != "categoryLeaderboard":
        return False
    category_data = module.get("category")
    return (
        isinstance(category_data, dict)
        and category_data.get("id") == _CATEGORY_IDS[category]
        and _clean_text(category_data.get("slug")) == category
        and category_data.get("active") is True
        and category_data.get("deprecated") is False
    )


def _publication_from_row(row: object) -> object:
    if not isinstance(row, dict):
        return None
    publication = row.get("publication")
    if isinstance(publication, dict):
        return publication
    user = row.get("user")
    if isinstance(user, dict):
        return user.get("primary_publication")
    return None


def _publication_item(publication: object) -> ListItem | None:
    if not isinstance(publication, dict):
        return None
    publication_id = str(publication.get("id") or "").strip()
    title = _clean_text(publication.get("name"))
    url = _publication_url(publication)
    if not publication_id.isdigit() or not title or not url:
        return None
    return ListItem(
        id=publication_id,
        title=title,
        author=_clean_text(publication.get("author_name")) or None,
        desc=_clean_text(publication.get("hero_text")) or None,
        cover=_https_url(publication.get("logo_url")),
        url=url,
        mobileUrl=url,
    )


def _publication_url(publication: dict) -> str:
    base_url = _https_url(publication.get("base_url"))
    if base_url:
        return base_url.rstrip("/")
    subdomain = _clean_text(publication.get("subdomain")).lower()
    if subdomain and all(char.isalnum() or char == "-" for char in subdomain):
        return f"https://{subdomain}.substack.com"
    return ""


def _https_url(value: object) -> str | None:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return url


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
