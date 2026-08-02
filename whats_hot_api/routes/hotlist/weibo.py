from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "weibo"

ROUTE_META: dict = {
    "name": "weibo",
    "title": "微博",
    "description": "实时热点，每分钟更新一次",
    "link": "https://s.weibo.com/top/summary/",
}

_API_URL = "https://weibo.com/ajax/statuses/hot_band"
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        headers={
            "Referer": "https://weibo.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        },
    )

    data = _parse_hot_band(result.data)
    return RouterData(
        **ROUTE_META,
        type="热搜榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _parse_hot_band(payload: object) -> list[ListItem]:
    if not isinstance(payload, dict) or payload.get("ok") != 1:
        return []
    body = payload.get("data") if isinstance(payload, dict) else None
    rows = body.get("band_list") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return []
        if row.get("is_ad") == 1:
            continue

        rank = _nonnegative_int(row.get("realpos"))
        hot = _nonnegative_int(row.get("num"))
        title = _clean_text(row.get("word"))
        if rank != len(data) + 1 or hot is None or not title:
            return []

        encoded_title = quote(f"#{title}#", safe="")
        url = f"https://s.weibo.com/weibo?q={encoded_title}"
        title_key = title.casefold()
        if title_key in seen_titles or url in seen_urls:
            return []
        seen_titles.add(title_key)
        seen_urls.add(url)

        description = _topic_description(row.get("word_scheme"), title)
        data.append(
            ListItem(
                id=title,
                title=title,
                desc=description,
                hot=hot,
                timestamp=get_time(row.get("onboard_time")),
                url=url,
                mobileUrl=url,
            )
        )

    return data if len(data) <= _MAX_ITEMS else []


def _nonnegative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _topic_description(value: object, title: str) -> str | None:
    description = _clean_text(value)
    if not description:
        return None
    normalized = description.strip("#").replace(" ", "").casefold()
    normalized_title = title.strip("#").replace(" ", "").casefold()
    return None if normalized == normalized_title else description
