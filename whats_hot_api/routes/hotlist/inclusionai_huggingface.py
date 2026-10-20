from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist.huggingface_releases import get_releases

ROUTE_NAME = 'inclusionai-huggingface'
SOURCE_LINK = 'https://huggingface.co/inclusionAI'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'inclusionAI',
    "description": 'inclusionAI model and organization updates.',
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    # Official Hugging Face account, one item per release (see utils/hf_releases.py).
    list_data = await get_releases("inclusionAI", no_cache)
    return RouterData(
        **ROUTE_META,
        type="Hugging Face",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )
