from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "guokr"

ROUTE_META: dict = {
    "name": "guokr",
    "title": "果壳",
    "description": "科技有意思",
    "link": "https://www.guokr.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://www.guokr.com/beta/proxy/science_api/articles?limit=30"
    result = await get(
        url=url,
        no_cache=no_cache,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        },
    )
    items = result.data if isinstance(result.data, list) else []
    data = [
        ListItem(
            id=v["id"],
            title=v["title"],
            desc=v.get("summary"),
            cover=v.get("small_image"),
            author=(v.get("author") or {}).get("nickname"),
            hot=None,
            badges=[{"text": "编辑推荐"}] if v.get("is_editor_recommend") is True else [],
            metrics=_reply_metrics(v),
            timestamp=get_time(v.get("date_modified")),
            url=f"https://www.guokr.com/article/{v['id']}",
            mobileUrl=f"https://m.guokr.com/article/{v['id']}",
        )
        for v in items
    ]
    return RouterData(
        **ROUTE_META,
        type="热门文章",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _reply_metrics(v: dict) -> dict[str, int] | None:
    # 回复数只收正整数,0 与缺失不进 metrics
    value = v.get("replies_count")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return {"replies": value}
    return None
