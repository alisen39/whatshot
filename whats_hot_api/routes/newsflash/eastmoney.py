from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_urls,
    content_status,
    metrics,
    to_int,
)

ROUTE_NAME = "eastmoney"

list_type: dict[str, dict[str, str]] = {
    "important": {"name": "重要", "column": "102"},
    "all": {"name": "全部", "column": "101"},
    "company": {"name": "公司", "column": "104"},
    "market": {"name": "市场", "column": "105"},
    "institution": {"name": "机构", "column": "106"},
    "macro": {"name": "宏观", "column": "107"},
}

SOURCE_LINK = "https://np.eastmoney.com/"

ROUTE_META: dict = {
    "name": "eastmoney",
    "title": "东方财富",
    "description": "东方财富 7x24 财经快讯",
    "params": {
        "type": {
            "name": "快讯频道",
            "type": {k: v["name"] for k, v in list_type.items()},
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "important")
    list_data = await _get_list(type_param, no_cache)
    type_info = list_type.get(type_param, list_type["important"])
    return RouterData(
        kind="newsflash",
        **{**ROUTE_META, "type": type_info["name"]},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    type_info = list_type.get(type_param, list_type["important"])
    column = type_info["column"]
    url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "client": "web",
            "biz": "web_724",
            "fastColumn": column,
            "sortEnd": "",
            "pageSize": "50",
            "req_trace": "1",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )

    raw = result.data or {}
    items = (raw.get("data") or {}).get("fastNewsList") or []
    data: list[NewsFlashItem] = []
    for it in items:
        code = it.get("code") or ""
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        if not title and not summary:
            continue
        content = summary or title
        data.append(
            NewsFlashItem(
                id=code or f"eastmoney-{len(data)}",
                title=title or summary[:60],
                content=content,
                summary=summary if summary and summary != title else None,
                contentStatus=content_status(content, fallback="summary"),
                source="东方财富",
                isImportant=type_param == "important",
                images=compact_urls(it.get("image")),
                symbols=compact_objects(it.get("stockList")),
                metrics=metrics(
                    commentCount=to_int(it.get("pinglun_Num")),
                    shareCount=to_int(it.get("share")),
                    sortScore=to_int(it.get("realSort")),
                ),
                timestamp=get_time(it.get("showTime")),
                url=SOURCE_LINK,
                mobileUrl=SOURCE_LINK,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
