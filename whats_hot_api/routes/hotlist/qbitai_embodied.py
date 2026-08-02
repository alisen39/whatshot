from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.rsshub import fetch_rsshub_feed

ROUTE_NAME = 'qbitai-embodied'
SOURCE_LINK = 'https://www.qbitai.com/tag/%E5%85%B7%E8%BA%AB%E6%99%BA%E8%83%BD'
RSSHUB_ROUTE = '/qbitai/tag/具身智能'
RSSHUB_PARAMS: dict[str, str | int | bool] = {}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": '量子位 · 具身智能',
    "description": 'Chinese coverage tagged for embodied AI from QbitAI.',
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await fetch_rsshub_feed(
        route_name=ROUTE_NAME,
        route_path=RSSHUB_ROUTE,
        params=RSSHUB_PARAMS,
        no_cache=no_cache,
    )
    return RouterData(
        **ROUTE_META,
        type="RSSHub",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )
