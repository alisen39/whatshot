from __future__ import annotations

import hashlib
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_strings,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "cls"

SOURCE_LINK = "https://www.cls.cn/telegraph"

_BASE_PARAMS: dict[str, str] = {
    "app": "CailianpressWeb",
    "os": "web",
    "sv": "8.7.9",
    "rn": "50",
    "refresh_type": "1",
}
TYPE_MAP = {
    "telegraph": "电报",
    "red": "加红",
    "announcement": "公司",
    "watch": "看盘",
    "hk-us": "港美股",
    "fund": "基金",
    "remind": "提醒",
    "depth": "深度",
    "hot": "热门",
}
_CATEGORY_BY_TYPE = {
    "red": "red",
    "announcement": "announcement",
    "watch": "watch",
    "hk-us": "hk_us",
    "fund": "fund",
    "remind": "remind",
}

ROUTE_META: dict = {
    "name": "cls",
    "title": "财联社",
    "description": "财联社实时电报快讯",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "快讯分类", "type": TYPE_MAP}},
}


def _signed_url(board_type: str = "telegraph") -> str:
    params = dict(_BASE_PARAMS)
    category = _CATEGORY_BY_TYPE.get(board_type)
    if category:
        params["category"] = category
    qs = urlencode(sorted(params.items()))
    sha1_value = hashlib.sha1(qs.encode(), usedforsecurity=False).hexdigest()
    sign = hashlib.md5(sha1_value.encode(), usedforsecurity=False).hexdigest()
    return f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "telegraph")
    board_type = requested_type if requested_type in TYPE_MAP else "telegraph"
    list_data = (
        await _get_article_list(board_type, no_cache)
        if board_type in {"depth", "hot"}
        else await _get_list(board_type, no_cache)
    )
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    url = _signed_url(board_type)
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    payload = result.data if isinstance(result.data, dict) else {}
    errno = payload.get("errno")
    if errno not in (None, 0):
        raise ValueError(
            f"CLS roll list returned errno={errno}: {payload.get('msg') or ''}"
        )
    items = (payload.get("data") or {}).get("roll_data") or []
    data: list[NewsFlashItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if truthy_flag(it.get("is_ad")):
            continue
        # type=-1 is the anonymous, complete public telegraph. Other values are
        # paid columns whose anonymous payload only contains a teaser.
        if it.get("type") != -1:
            continue
        title = (it.get("title") or "").strip()
        full_content = strip_html(it.get("content")).strip()
        brief = strip_html(it.get("brief")).strip()
        content = full_content or brief
        if not title and not content:
            continue
        item_id = it.get("id")
        id_str = str(item_id) if item_id else f"cls-{len(data)}"
        detail_url = f"https://www.cls.cn/detail/{item_id}" if item_id else SOURCE_LINK
        level = str(it.get("level") or "").strip()
        important = (
            truthy_flag(it.get("is_top"))
            or truthy_flag(it.get("bold"))
            or truthy_flag(it.get("recommend"))
            or level.upper() in {"A", "B"}
        )
        data.append(
            NewsFlashItem(
                id=id_str,
                title=title or content[:60],
                content=content,
                summary=brief if brief and brief != content else None,
                contentStatus=content_status(
                    content,
                    fallback="full" if full_content else "summary",
                ),
                source=(it.get("author") or "").strip() or None,
                isImportant=important,
                tags=(
                    compact_strings(it.get("tags"))
                    or compact_strings(
                        it.get("subjects"),
                        keys=(
                            "subject_name",
                            "name",
                            "title",
                            "text",
                            "label",
                            "tag_name",
                        ),
                    )
                    or compact_strings(it.get("sub_titles"))
                ),
                images=[
                    *compact_urls(it.get("images")),
                    *compact_urls(it.get("imgs")),
                    *compact_urls(it.get("img")),
                ],
                symbols=compact_objects(it.get("stock_list")) + compact_objects(it.get("plate_list")),
                metrics=metrics(
                    readingCount=to_int(it.get("reading_num")),
                    commentCount=to_int(it.get("comment_num")),
                    shareCount=to_int(it.get("share_num")),
                    explainCount=to_int(it.get("explain_num")),
                    level=level or None,
                ),
                timestamp=get_time(it.get("ctime")),
                url=detail_url,
                mobileUrl=it.get("shareurl") or detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_article_list(board_type: str, no_cache: bool) -> dict:
    endpoint = {
        "depth": "https://www.cls.cn/v3/depth/home/assembled/1000",
        "hot": "https://www.cls.cn/v2/article/hot/list",
    }[board_type]
    result = await get(
        url=f"{endpoint}?{_legacy_params()}",
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json", "Referer": SOURCE_LINK},
    )
    source_rows = ((result.data or {}).get("data") or {}).get("depth_list") if board_type == "depth" else (result.data or {}).get("data") or []
    rows = source_rows if isinstance(source_rows, list) else []
    if board_type == "depth":
        rows.sort(key=lambda row: row.get("ctime") or 0, reverse=True)
    data = [_article_item(row, board_type) for row in rows]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": [item for item in data if item is not None]}


def _legacy_params() -> str:
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5"}
    qs = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    sha1_value = hashlib.sha1(qs.encode(), usedforsecurity=False).hexdigest()
    return f"{qs}&sign={hashlib.md5(sha1_value.encode(), usedforsecurity=False).hexdigest()}"


def _article_item(row: object, board_type: str) -> NewsFlashItem | None:
    if not isinstance(row, dict):
        return None
    item_id = row.get("id")
    title = str(row.get("title") or row.get("brief") or "").strip()
    content = strip_html(row.get("content") or row.get("brief")).strip()
    if not item_id or not title:
        return None
    url = f"https://www.cls.cn/detail/{item_id}"
    return NewsFlashItem(
        id=str(item_id), title=title, content=content or title,
        summary=content if content and content != title else None,
        contentStatus=content_status(content or title, fallback="summary"),
        source="财联社", tags=[TYPE_MAP[board_type]], timestamp=get_time(row.get("ctime")),
        url=url, mobileUrl=row.get("shareurl") or url,
    )
