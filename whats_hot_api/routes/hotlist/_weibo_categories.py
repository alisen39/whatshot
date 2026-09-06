from __future__ import annotations

import re
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.cache import cache
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

_GENVISITOR_URL = "https://passport.weibo.com/visitor/genvisitor"
_INCARNATE_URL = "https://passport.weibo.com/visitor/visitor"
_BOARD_URL = "https://weibo.com/ajax/statuses/{endpoint}"
_COOKIE_CACHE_KEY = "weibo:visitor:cookie"
# 匿名访客 SUB 上游有效期约 6 个月；缓存 1 小时以便六条分类榜共享同一访客会话，
# 过期后最迟 1 小时内自动重建。
_COOKIE_CACHE_TTL = 3600
_MAX_ITEMS = 50

_HEADERS = {
    "Referer": "https://weibo.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
}


async def handle_category(
    endpoint: str, meta: dict, request: Request, no_cache: bool = False
) -> RouterData:
    cookie = await _visitor_cookie(no_cache)
    result = await get(
        url=_BOARD_URL.format(endpoint=endpoint),
        no_cache=no_cache,
        headers={**_HEADERS, "Cookie": cookie},
    )

    data = _parse_band(result.data)
    return RouterData(
        **meta,
        type="热搜榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


async def _visitor_cookie(no_cache: bool) -> str:
    # tid 单次有效，genvisitor 不缓存；incarnate 结果缓存以复用访客会话。
    # 缓存有效时直接复用，避免每条分类榜请求都向 passport 发起一次引导。
    if not no_cache:
        cached = await cache.get(_COOKIE_CACHE_KEY)
        cookie = _cookie_from_incarnate_text(cached.data if cached is not None else None)
        if cookie is not None:
            return cookie

    gen_result = await post(
        url=_GENVISITOR_URL,
        no_cache=True,
        response_type="text",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body="cb=gen_callback",
    )
    tid = _jsonp_value(gen_result.data, "tid")
    if tid is None:
        raise RuntimeError("weibo visitor bootstrap: genvisitor returned no tid")

    incarnate_result = await get(
        url=_INCARNATE_URL,
        params={"a": "incarnate", "t": tid, "cb": "cross_domain"},
        no_cache=no_cache,
        response_type="text",
        ttl=_COOKIE_CACHE_TTL,
        cache_key=_COOKIE_CACHE_KEY,
    )
    cookie = _cookie_from_incarnate_text(incarnate_result.data)
    if cookie is None:
        raise RuntimeError("weibo visitor bootstrap: incarnate returned no sub/subp")
    return cookie


def _jsonp_value(text: object, key: str) -> str | None:
    if not isinstance(text, str):
        return None
    match = re.search(rf'"{key}":"([^"]+)"', text)
    return match.group(1) if match else None


def _cookie_from_incarnate_text(text: object) -> str | None:
    sub = _jsonp_value(text, "sub")
    subp = _jsonp_value(text, "subp")
    if sub is None or subp is None:
        return None
    return f"SUB={sub}; SUBP={subp}"


def _parse_band(payload: object) -> list[ListItem]:
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
