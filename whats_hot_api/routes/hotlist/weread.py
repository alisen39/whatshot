from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.tokens.weread import get_weread_id

ROUTE_NAME = "weread"

type_map: dict[str, str] = {
    "rising": "飙升榜",
    "hot_search": "热搜榜",
    "newbook": "新书榜",
    "general_novel_rising": "小说榜",
    "all": "总榜",
    "newrating_publish": "神作榜",
    "newrating_potential_publish": "神作潜力榜",
    "1900000": "男生小说榜",
    "2000000": "女生小说榜",
}

ROUTE_META: dict = {
    "name": "weread",
    "title": "微信读书",
    "params": {
        "type": {
            "name": "排行榜分区",
            "type": type_map,
        },
    },
    "link": "https://weread.qq.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "rising")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "飙升榜"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    # 网页脚本按分类决定带不带 rank=1;实测规则:非数字的榜单 id(如 newrating_publish)
    # 必须带,数字分类 id(如 1900000)带了反而返回 0 本
    rank_suffix = "?rank=1" if not type_param.isdigit() else ""
    url = f"https://weread.qq.com/web/bookListInCategory/{type_param}{rank_suffix}"
    result = await get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.67",
        },
        no_cache=no_cache,
    )
    items = result.data["books"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            _book_item(v, position)
            for position, v in enumerate(items, start=1)
        ],
    }


def _book_item(row: dict, position: int) -> ListItem:
    info = row["bookInfo"]
    rating = info.get("newRating")
    rating_count = info.get("newRatingCount")
    wordmark = (info.get("newRatingDetail") or {}).get("title") if isinstance(info.get("newRatingDetail"), dict) else None
    metrics: dict[str, int] = {}
    if isinstance(rating, int) and rating > 0:
        metrics["rating"] = rating  # 832 即 8.32 分
    if isinstance(rating_count, int) and rating_count > 0:
        metrics["ratingCount"] = rating_count
    rise = row.get("riseCount")
    if isinstance(rise, int) and not isinstance(rise, bool) and rise != 0:
        metrics["rise"] = rise
    badges: list[dict] = []
    if wordmark:
        badges.append({"text": str(wordmark)})
    if info.get("finished") == 1:
        badges.append({"text": "完结"})
    book_id = info["bookId"]
    detail_url = f"https://weread.qq.com/web/bookDetail/{get_weread_id(book_id)}"
    return ListItem(
        id=book_id,
        title=info["title"],
        author=info.get("author"),
        desc=info.get("intro"),
        cover=(info.get("cover") or "").replace("s_", "t9_") or None,
        timestamp=get_time(info.get("publishTime")),
        hot=row.get("readingCount"),
        hotLabel="阅读",
        badges=badges or [],
        metrics=metrics or None,
        sourceRank=position,
        url=detail_url,
        mobileUrl=detail_url,
    )
