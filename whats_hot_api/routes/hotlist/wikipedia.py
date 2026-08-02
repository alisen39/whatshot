from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "wikipedia"

type_map: dict[str, str] = {
    "zh": "中文昨日阅读榜",
    "en": "英文昨日阅读榜",
    "ja": "日文昨日阅读榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Wikipedia",
    "description": "Wikipedia 昨日阅读量最高的条目",
    "params": {"type": {"name": "语言", "type": type_map}},
    "link": "https://www.wikipedia.org/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "zh")
    selected_type = type_param if type_param in type_map else "zh"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(lang: str, no_cache: bool) -> dict:
    target_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    date_path = target_date.strftime("%Y/%m/%d")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/feed/featured/{date_path}"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    rows = ((result.data or {}).get("mostread") or {}).get("articles") or []
    data = [_article_item(row, lang) for row in rows]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _article_item(row: dict, lang: str) -> ListItem | None:
    title = str(row.get("normalizedtitle") or row.get("title") or "").strip()
    if not title:
        return None
    urls = row.get("content_urls") if isinstance(row.get("content_urls"), dict) else {}
    desktop = urls.get("desktop") if isinstance(urls.get("desktop"), dict) else {}
    url = str(desktop.get("page") or "").strip()
    if not url:
        slug = quote(title.replace(" ", "_"), safe="()_-")
        url = f"https://{lang}.wikipedia.org/wiki/{slug}"
    thumbnail = row.get("thumbnail") if isinstance(row.get("thumbnail"), dict) else {}
    description = str(row.get("description") or "").strip()
    extract = str(row.get("extract") or "").strip()
    return ListItem(
        id=str(row.get("pageid") or row.get("title") or title),
        title=title,
        desc=description or extract[:240] or None,
        hot=row.get("views"),
        cover=str(thumbnail.get("source") or "").strip() or None,
        url=url,
        mobileUrl=url,
    )
