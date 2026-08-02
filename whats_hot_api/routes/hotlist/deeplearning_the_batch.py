from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.rsshub import fetch_rsshub_feed

ROUTE_NAME = 'deeplearning-the-batch'
SOURCE_LINK = 'https://www.deeplearning.ai/the-batch/'
RSSHUB_ROUTE = '/deeplearning/the-batch'
RSSHUB_PARAMS: dict[str, str | int | bool] = {}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'DeepLearning.AI · The Batch',
    "description": 'Accessible AI news and analysis from DeepLearning.AI.',
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
