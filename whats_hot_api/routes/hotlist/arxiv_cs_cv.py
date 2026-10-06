from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.routes.hotlist import _arxiv_common
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "arxiv-cs-cv"
CATEGORY = "cs.CV"
SOURCE_LINK = "https://arxiv.org/list/cs.CV/new"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "arXiv · cs.CV",
    "description": "arXiv cs.CV 最近一次公告:新投稿、交叉投稿、替换版本。",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": {"cs-cv": "cs.CV"},
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新公告 · cs.CV",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


async def _get_list(no_cache: bool) -> dict:
    async def _fetch():
        return await get(
            url=f"https://arxiv.org/list/{CATEGORY}/new",
            params={"skip": 0, "show": 2000},
            no_cache=no_cache,
            response_type="text",
            headers=_arxiv_common.arxiv_headers(),
        )

    result = await _arxiv_common.fetch_with_spacing(_fetch)
    heading, entries = _arxiv_common.parse_new_listing(result.data)
    if not entries:
        raise RuntimeError("arXiv cs.CV listing page did not contain any entries")
    heading = _arxiv_common.check_listing_total(result.data, len(entries), "cs.CV", heading)
    data = [
        ListItem(
            id=e["id"],
            title=e["title"],
            url=f"https://arxiv.org/abs/{e['id']}",
            mobileUrl=f"https://arxiv.org/abs/{e['id']}",
            author=e["author"],
            desc=e["desc"],
        )
        for e in entries
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "message": heading or None,
    }
