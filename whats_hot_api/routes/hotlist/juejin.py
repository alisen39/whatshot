from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "juejin"

_RECOMMEND_CATEGORIES = {
    "recommend-backend": ("后端推荐", "6809637769959178254"),
    "recommend-frontend": ("前端推荐", "6809637767543259144"),
    "recommend-ai": ("人工智能推荐", "6809637773935378440"),
}

_SEED_TYPES = {
    "1": "综合",
    "hot": "全站热榜",
    "recommend": "首页推荐",
    **{key: value[0] for key, value in _RECOMMEND_CATEGORIES.items()},
}

ROUTE_META: dict = {
    "name": "juejin",
    "title": "稀土掘金",
    "link": "https://juejin.cn/hot/articles",
    # Categories are fetched at runtime; advertise the always-present seed.
    "params": {"type": {"name": "排行榜分区", "type": _SEED_TYPES}},
}

# Categories are fetched at runtime, so type values are not a fixed enum;
# skip strict validation (any category_id is accepted by the upstream).
ROUTE_VALIDATE_TYPE = False

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def _get_category() -> dict[str, str]:
    category_url = "https://api.juejin.cn/tag_api/v1/query_category_briefs"
    res = await get(url=category_url, headers=_HEADERS)
    items = res.data.get("data", []) if res.data else []
    type_obj: dict[str, str] = dict(_SEED_TYPES)
    for c in items:
        type_obj[c["category_id"]] = c["category_name"]
    return type_obj


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "1")
    if type_param == "hot":
        list_data = await _get_global_hot(no_cache)
        return RouterData(
            **ROUTE_META,
            type=_SEED_TYPES[type_param],
            total=len(list_data["data"]),
            fromCache=list_data["from_cache"],
            updateTime=list_data["update_time"],
            data=list_data["data"],
        )
    if type_param == "recommend" or type_param in _RECOMMEND_CATEGORIES:
        category = _RECOMMEND_CATEGORIES.get(type_param)
        list_data = await _get_recommend(
            no_cache, category_id=category[1] if category else None
        )
        type_maps = await _get_category()
        return RouterData(
            **{**ROUTE_META, "params": {"type": {"name": "排行榜分区", "type": type_maps}}},
            type=category[0] if category else "首页推荐",
            total=len(list_data["data"]),
            fromCache=list_data["from_cache"],
            updateTime=list_data["update_time"],
            data=list_data["data"],
        )
    url = f"https://api.juejin.cn/content_api/v1/content/article_rank?category_id={type_param}&type=hot"
    result = await get(url=url, no_cache=no_cache, headers=_HEADERS)
    items = result.data.get("data", [])
    type_maps = await _get_category()
    data = [
        ListItem(
            id=v["content"]["content_id"],
            title=v["content"]["title"],
            author=v["author"]["name"],
            desc=v["content"].get("brief") or None,
            hot=v["content_counter"]["hot_rank"],
            timestamp=None,  # upstream ctime is always 0
            url=f"https://juejin.cn/post/{v['content']['content_id']}",
            mobileUrl=f"https://juejin.cn/post/{v['content']['content_id']}",
        )
        for v in items
    ]
    return RouterData(
        **{**ROUTE_META, "params": {"type": {"name": "排行榜分区", "type": type_maps}}},
        type="文章榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


async def _get_global_hot(no_cache: bool) -> dict:
    result = await get(
        url="https://api.juejin.cn/content_api/v1/content/article_rank",
        params={"category_id": "1", "type": "hot"},
        no_cache=no_cache,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json"},
        cache_key="whatshot:juejin:global-hot",
    )
    data: list[ListItem] = []
    for row in (result.data or {}).get("data", []):
        content = row.get("content") if isinstance(row, dict) else None
        counter = row.get("content_counter") if isinstance(row, dict) else None
        content = content if isinstance(content, dict) else {}
        counter = counter if isinstance(counter, dict) else {}
        article_id = str(content.get("content_id") or "").strip()
        title = str(content.get("title") or "").strip()
        if not article_id or not title:
            continue
        url = f"https://juejin.cn/post/{article_id}"
        data.append(ListItem(
            id=f"juejin-{article_id}",
            title=title,
            desc=str(content.get("brief_content") or "").strip() or None,
            hot=counter.get("hot_rank") or counter.get("like"),
            cover=content.get("cover_image") or content.get("pic") or content.get("screenshot"),
            url=url,
            mobileUrl=url,
        ))
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _get_recommend(no_cache: bool, category_id: str | None = None) -> dict:
    url = (
        "https://api.juejin.cn/recommend_api/v1/article/recommend_cate_feed"
        if category_id
        else "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
    )
    body = {
        "id_type": 2,
        "sort_type": 200,
        "limit": 50,
        "cursor": "0",
    }
    if category_id:
        body["cate_id"] = category_id
    else:
        body["client_type"] = 2608
    result = await post(
        url=url,
        body=body,
        no_cache=no_cache,
        headers={**_HEADERS, "Content-Type": "application/json"},
    )
    data: list[ListItem] = []
    for row in (result.data or {}).get("data", []):
        item_info = None
        if isinstance(row, dict):
            item_info = row.get("item_info") or row
        if not isinstance(item_info, dict):
            continue
        article = item_info.get("article_info") or {}
        author = item_info.get("author_user_info") or {}
        article_id = str(article.get("article_id") or "").strip()
        title = str(article.get("title") or "").strip()
        if not article_id or not title:
            continue
        tags = [
            str(tag.get("tag_name") or "").strip()
            for tag in item_info.get("tags", [])
            if isinstance(tag, dict) and str(tag.get("tag_name") or "").strip()
        ]
        url = f"https://juejin.cn/post/{article_id}"
        data.append(
            ListItem(
                id=article_id,
                title=title,
                author=author.get("user_name"),
                desc=" · ".join(
                    part
                    for part in [
                        str(article.get("brief_content") or "").strip() or None,
                        "标签：" + "、".join(tags[:6]) if tags else None,
                    ]
                    if part
                )
                or None,
                hot=article.get("digg_count"),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
