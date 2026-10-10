from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "lol"

ROUTE_META: dict = {
    "name": "lol",
    "title": "英雄联盟",
    "link": "https://lol.qq.com/gicp/news/423/2/1334/1.html",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="更新公告",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://apps.game.qq.com/cmc/zmMcnTargetContentList?r0=json&page=1&num=30&target=24&source=web_pc"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", {}).get("result", [])
    data = [
        ListItem(
            id=v.get("iDocID", ""),
            title=v.get("sTitle", ""),
            cover=f"https:{v.get('sIMG', '')}" if v.get("sIMG") else None,
            author=v.get("sAuthor") or None,
            hot=int(v["iTotalPlay"]) if v.get("iTotalPlay") else None,
            hotLabel="播放",
            # 置顶只有 "1" 一种取值,其余一律不设
            isPinned=True if v.get("iTop") == "1" else None,
            metrics=_count_metrics(v),
            timestamp=get_time(v.get("sCreated", "")),
            url=f"https://lol.qq.com/news/detail.shtml?docid={quote(v.get('iDocID', ''))}",
            mobileUrl=f"https://lol.qq.com/news/detail.shtml?docid={quote(v.get('iDocID', ''))}",
        )
        for v in items
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


def _count_metrics(v: dict) -> dict[str, int] | None:
    # 互动计数只收正整数;接口对 0 与缺失不区分,均不进 metrics
    metrics: dict[str, int] = {}
    for source_key, metric_key in (("iCmtNum", "comments"), ("iLikeNum", "likes"), ("iCollectionNum", "favorites"), ("iShareNum", "shares")):
        value = v.get(source_key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            metrics[metric_key] = value
    return metrics or None
