from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "tiktok"

type_map: dict[str, str] = {
    "hashtags": "美国近 7 日热门话题",
    "videos": "美国近 30 日热门视频",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "TikTok",
    "description": "TikTok Creative Center 官方美国区热门话题与视频",
    "params": {
        "type": {
            "name": "趋势榜",
            "type": type_map,
        },
    },
    "link": "https://ads.tiktok.com/creative/creativeCenter/trends",
}

_PORTAL_ORIGIN = "https://ads.tiktok.com"
_US_ORIGIN = "https://ads.us.tiktok.com"
_HASHTAG_URL = f"{_PORTAL_ORIGIN}/CreativeOne/KnowledgeAPI/GetHashtagList"
_OVERVIEW_URL = f"{_US_ORIGIN}/CreativeOne/Report/GetTopContentsOverview"
_VIDEO_URL = f"{_US_ORIGIN}/CreativeOne/Report/CreativeCenterGetTopContentsList"
_HASHTAG_BODY = {
    "timeRange": 7,
    "countryCode": "US",
    "page": 1,
    "limit": 20,
}
_MAX_ITEMS = 20


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hashtags")
    selected_type = type_param if type_param in type_map else "hashtags"
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
    if board_type == "videos":
        return await _get_videos(no_cache)
    return await _get_hashtags(no_cache)


async def _get_hashtags(no_cache: bool) -> dict:
    result = await post(
        url=_HASHTAG_URL,
        body=_HASHTAG_BODY,
        no_cache=no_cache,
        cache_key="tiktok:creative-center:hashtags:us:7d",
        headers=_headers("hashtag"),
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_hashtags(result.data),
    }


async def _get_videos(no_cache: bool) -> dict:
    overview = await get(
        url=_OVERVIEW_URL,
        no_cache=no_cache,
        cache_key="tiktok:creative-center:video-overview:us",
        headers=_headers("video"),
    )
    period_end = _daily_period_end(overview.data)
    if period_end is None:
        return {
            "from_cache": overview.from_cache,
            "update_time": overview.update_time,
            "data": [],
        }
    result = await get(
        url=_VIDEO_URL,
        no_cache=no_cache,
        cache_key="tiktok:creative-center:videos:us:30d:views",
        headers=_headers("video"),
        params={
            "periodDimension": 5,
            "periodEndTimestamp": period_end,
            "orderByMetric": 1,
            "countryCode": "US",
            "contentLabelIDs": "",
            "organicOnly": False,
            "limit": 20,
            "page": 1,
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_videos(result.data),
    }


def _parse_hashtags(payload: object) -> list[ListItem]:
    if not _successful_payload(payload):
        return []
    rows = payload.get("items")
    pagination = payload.get("pagination")
    if not isinstance(rows, list) or not _valid_pagination(pagination, len(rows)):
        return []
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for rank, row in enumerate(rows, 1):
        item = _hashtag_item(row, rank)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _hashtag_item(value: object, expected_rank: int) -> ListItem | None:
    if not isinstance(value, dict) or value.get("rankIndex") != expected_rank:
        return None
    hashtag_id = _digits(value.get("hashtagID"))
    name = _clean_text(value.get("hashtagName"))
    posts = _nonnegative_int(value.get("publishCnt"))
    views = _nonnegative_int(value.get("vv"))
    curve = value.get("popularityCurve")
    if (
        hashtag_id is None
        or not name
        or posts is None
        or views is None
        or not _valid_seven_day_curve(curve)
    ):
        return None
    url = (
        f"{_PORTAL_ORIGIN}/creative/creativeCenter/trends/hashtag/"
        f"{hashtag_id}?period=7&region=US"
    )
    return ListItem(
        id=hashtag_id,
        title=f"#{name}",
        desc=f"近 7 日发布量：{posts}",
        hot=views,
        url=url,
        mobileUrl=url,
    )


def _parse_videos(payload: object) -> list[ListItem]:
    if not _successful_payload(payload):
        return []
    rows = payload.get("entityInfos")
    pagination = payload.get("pagination")
    if not isinstance(rows, list) or not _valid_pagination(pagination, len(rows)):
        return []
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    previous_views: int | None = None
    for row in rows:
        item = _video_item(row)
        if item is None or item.id in seen_ids:
            continue
        if previous_views is not None and (item.hot or 0) > previous_views:
            return []
        seen_ids.add(item.id)
        previous_views = item.hot or 0
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _video_item(value: object) -> ListItem | None:
    if not isinstance(value, dict):
        return None
    info = value.get("itemInfo")
    author = value.get("itemAuthorInfo")
    metrics = value.get("itemMetrics")
    if not isinstance(info, dict) or not isinstance(author, dict) or not isinstance(metrics, dict):
        return None
    item_id = _digits(info.get("itemID"))
    username = _clean_text(author.get("handlerName"))
    title = _clean_text(info.get("title"))
    views = _nonnegative_int(metrics.get("videoViews"))
    timestamp = get_time(info.get("createTime"))
    if (
        item_id is None
        or info.get("contentType") != 1
        or not username
        or not title
        or views is None
        or timestamp is None
        or timestamp <= 0
    ):
        return None

    desc_parts: list[str] = []
    author_metrics = value.get("itemAuthorMetrics")
    followers = _nonnegative_int(author_metrics.get("followers")) if isinstance(author_metrics, dict) else None
    if followers is not None:
        desc_parts.append(f"粉丝：{followers}")
    tags = value.get("contentTags")
    if isinstance(tags, list):
        names = [_clean_text(tag.get("contentLabelName")) for tag in tags if isinstance(tag, dict)]
        names = [name for name in names if name]
        if names:
            desc_parts.append("分类：" + "、".join(names))
    url = f"https://www.tiktok.com/@{username}/video/{item_id}"
    return ListItem(
        id=item_id,
        title=title,
        author=username,
        desc=" · ".join(desc_parts) or None,
        hot=views,
        timestamp=timestamp,
        url=url,
        mobileUrl=url,
    )


def _daily_period_end(payload: object) -> int | None:
    if not _successful_payload(payload):
        return None
    value = _positive_int(payload.get("lastDailyEndTimestamp"))
    return value if value is not None and value < 10**12 else None


def _successful_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    base = payload.get("BaseResp")
    return (
        isinstance(base, dict)
        and base.get("StatusCode") == 0
        and _clean_text(base.get("StatusMessage")) == ""
    )


def _valid_pagination(value: object, row_count: int) -> bool:
    if not isinstance(value, dict) or value.get("page") != 1:
        return False
    limit = _positive_int(value.get("limit"))
    total = _nonnegative_int(value.get("totalCount"))
    return limit is not None and total is not None and row_count <= limit and total >= row_count


def _valid_seven_day_curve(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 7:
        return False
    timestamps: list[int] = []
    for point in value:
        if not isinstance(point, dict):
            return False
        timestamp = _positive_int(point.get("timestamp"))
        score = point.get("value")
        if timestamp is None or not isinstance(score, (int, float)) or score < 0:
            return False
        timestamps.append(timestamp)
    return all(b - a == 86400 for a, b in zip(timestamps, timestamps[1:]))


def _headers(tab: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": _PORTAL_ORIGIN,
        "Referer": f"{_PORTAL_ORIGIN}/creative/creativeCenter/trends/{tab}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


def _digits(value: object) -> str | None:
    text = _clean_text(value)
    return text if text.isdigit() and int(text) > 0 else None


def _positive_int(value: object) -> int | None:
    number = _nonnegative_int(value)
    return number if number is not None and number > 0 else None


def _nonnegative_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
