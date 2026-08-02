from __future__ import annotations

import re
import time
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "nowcoder"

SOURCE_LINK = "https://www.nowcoder.com/"
_API_BASE = "https://gw-c.nowcoder.com/api/sparta"

type_map: dict[str, str] = {
    "trending": "热门帖子",
    "hot-search": "热搜词",
    "topics": "热门话题",
    "recommend": "首页推荐",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "牛客",
    "description": "牛客热门内容、热搜词与话题",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "trending")
    selected_type = type_param if type_param in type_map else "trending"
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
    if board_type == "hot-search":
        return await _get_hot_search(no_cache)
    if board_type == "topics":
        return await _get_topics(no_cache)
    if board_type == "recommend":
        return await _get_recommend(no_cache)
    return await _get_trending(no_cache)


async def _get_trending(no_cache: bool) -> dict:
    url = f"{_API_BASE}/hot-search/top-hot-pc"
    result = await _request(
        url,
        no_cache,
        params={"size": "20", "_": str(int(time.time() * 1000)), "t": ""},
        cache_key=f"{url}?size=20",
    )
    rows = ((result.data or {}).get("data") or {}).get("result") or []
    data: list[ListItem] = []
    for row in rows:
        title = _text(row.get("title"))
        item_url = _trending_url(row)
        if not title or not item_url:
            continue
        data.append(
            ListItem(
                id=str(row.get("uuid") or row.get("id") or item_url),
                title=title,
                desc=_text(row.get("desc")) or None,
                hot=row.get("hotValueFromDolphin"),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return _result(result, data)


async def _get_hot_search(no_cache: bool) -> dict:
    url = f"{_API_BASE}/hot-search/hot-content"
    result = await _request(url, no_cache)
    rows = ((result.data or {}).get("data") or {}).get("hotQuery") or []
    data: list[ListItem] = []
    for row in rows:
        query = _text(row.get("query"))
        if not query or row.get("ad"):
            continue
        item_url = f"https://www.nowcoder.com/search/all?query={quote(query)}"
        data.append(
            ListItem(
                id=query,
                title=query,
                hot=row.get("hotValue"),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return _result(result, data)


async def _get_topics(no_cache: bool) -> dict:
    url = f"{_API_BASE}/subject/hot-subject"
    result = await _request(url, no_cache)
    payload = (result.data or {}).get("data") or {}
    rows = payload.get("result") or [] if isinstance(payload, dict) else payload
    data: list[ListItem] = []
    for row in rows:
        topic_id = _text(row.get("uuid"))
        title = _text(row.get("content"))
        if not topic_id or not title:
            continue
        item_url = f"https://www.nowcoder.com/creation/subject/{topic_id}"
        desc_parts = []
        if row.get("viewCount") is not None:
            desc_parts.append(f"浏览：{row['viewCount']}")
        if row.get("momentCount") is not None:
            desc_parts.append(f"帖子：{row['momentCount']}")
        data.append(
            ListItem(
                id=topic_id,
                title=title,
                desc=" · ".join(desc_parts) or None,
                hot=row.get("hotValue"),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return _result(result, data)


async def _get_recommend(no_cache: bool) -> dict:
    url = f"{_API_BASE}/home/recommend"
    result = await _request(
        url,
        no_cache,
        params={"page": "1", "size": "50"},
        cache_key=f"{url}?page=1&size=50",
    )
    rows = ((result.data or {}).get("data") or {}).get("records") or []
    data = [_recommend_item(row) for row in rows]
    return _result(result, [item for item in data if item is not None])


async def _request(
    url: str,
    no_cache: bool,
    *,
    params: dict[str, str] | None = None,
    cache_key: str | None = None,
):
    return await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        params=params,
        cache_key=cache_key,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )


def _recommend_item(row: dict) -> ListItem | None:
    content = next(
        (
            value
            for key in ("momentData", "longContentData", "contentData")
            if isinstance((value := row.get(key)), dict)
        ),
        None,
    )
    if content is None:
        return None
    title = _text(content.get("title") or content.get("newTitle"))
    item_id = _text(content.get("uuid") or content.get("id") or row.get("contentId"))
    if not title or not item_id:
        return None

    if row.get("momentData") is content:
        item_url = f"https://www.nowcoder.com/feed/main/detail/{item_id}"
    else:
        discuss_id = _text(content.get("id") or row.get("contentId"))
        if not discuss_id:
            return None
        item_url = f"https://www.nowcoder.com/discuss/{discuss_id}"

    frequency = row.get("frequencyData")
    frequency = frequency if isinstance(frequency, dict) else {}
    user = row.get("userBrief")
    user = user if isinstance(user, dict) else {}
    desc_parts = []
    for key, label in (("viewCnt", "浏览"), ("likeCnt", "点赞"), ("commentCnt", "评论")):
        if frequency.get(key) is not None:
            desc_parts.append(f"{label}：{frequency[key]}")
    excerpt = _plain_text(content.get("content") or content.get("newContent"))
    if excerpt:
        desc_parts.append(excerpt[:120])
    return ListItem(
        id=item_id,
        title=title,
        author=_text(user.get("nickname")) or None,
        desc=" · ".join(desc_parts) or None,
        hot=frequency.get("viewCnt"),
        timestamp=get_time(
            content.get("showTime")
            or content.get("createTime")
            or content.get("createdAt")
        ),
        url=item_url,
        mobileUrl=item_url,
    )


def _trending_url(item: dict) -> str | None:
    item_type = item.get("type")
    if item_type == 74 and item.get("uuid"):
        return f"https://www.nowcoder.com/feed/main/detail/{item['uuid']}"
    if item_type == 0 and item.get("id"):
        return f"https://www.nowcoder.com/discuss/{item['id']}"
    router = item.get("router")
    if isinstance(router, str) and router:
        return router if router.startswith("http") else f"https://www.nowcoder.com{router}"
    return None


def _result(result, data: list[ListItem]) -> dict:
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _text(value: object) -> str:
    return str(value or "").strip()


def _plain_text(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _text(value))).strip()
