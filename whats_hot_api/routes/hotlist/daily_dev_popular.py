from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.rsshub import fetch_rsshub_feed

ROUTE_NAME = 'daily-dev-popular'
SOURCE_LINK = 'https://app.daily.dev/'
RSSHUB_ROUTE = '/daily/popular'
RSSHUB_PARAMS: dict[str, str | int | bool] = {}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'daily.dev · Popular',
    "description": 'Popular developer articles aggregated by daily.dev.',
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
