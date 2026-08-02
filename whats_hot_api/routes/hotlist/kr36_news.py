from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.rsshub import fetch_rsshub_feed

ROUTE_NAME = '36kr-news'
SOURCE_LINK = 'https://36kr.com/'
RSSHUB_ROUTE = '/36kr/news/latest'
RSSHUB_PARAMS: dict[str, str | int | bool] = {}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": '36Kr Latest',
    "description": 'Chinese startup and technology business headlines.',
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
