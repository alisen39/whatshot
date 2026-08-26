from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, NewsFlashItem, RouterData
from whats_hot_api.utils.rsshub import fetch_rsshub_feed

ROUTE_NAME = "anthropic-engineering"
SOURCE_LINK = "https://www.anthropic.com/engineering"
RSSHUB_ROUTE = "/anthropic/engineering"
RSSHUB_PARAMS: dict[str, str | int | bool] = {}
TYPE_MAP = {"engineering": "Engineering"}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Anthropic Engineering",
    "description": "Anthropic 官方工程实践与技术更新",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": TYPE_MAP,
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "engineering")
    board_type = requested_type if requested_type in TYPE_MAP else "engineering"
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await fetch_rsshub_feed(
        route_name=ROUTE_NAME,
        route_path=RSSHUB_ROUTE,
        params=RSSHUB_PARAMS,
        no_cache=no_cache,
    )
    data = [_as_newsflash(item) for item in result["data"]]
    if not data:
        raise RuntimeError("Anthropic Engineering feed contained no usable items")
    return {
        "from_cache": result["from_cache"],
        "update_time": result["update_time"],
        "data": data,
    }


def _as_newsflash(item: ListItem) -> NewsFlashItem:
    content = item.desc or item.title
    return NewsFlashItem(
        id=item.id,
        title=item.title,
        content=content,
        summary=item.desc,
        contentStatus="summary",
        source="Anthropic",
        tags=["Engineering"],
        images=[item.cover] if item.cover else [],
        timestamp=item.timestamp,
        url=item.url,
        mobileUrl=item.mobileUrl or item.url,
    )
