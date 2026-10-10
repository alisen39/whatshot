from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qq-news"

ROUTE_META: dict = {
    "name": "qq-news",
    "title": "腾讯新闻",
    "link": "https://news.qq.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://r.inews.qq.com/gw/event/hot_ranking_list?page_size=50"
    result = await get(url=url, no_cache=no_cache)
    id_list = result.data.get("idlist", [])
    news_list = id_list[0].get("newslist", []) if id_list else []
    # Skip first item as in the TS source
    items = news_list[1:]
    data = [
        _news_item(v, position)
        for position, v in enumerate(items, start=1)
    ]
    return RouterData(
        **ROUTE_META,
        type="热点榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _count(value: object) -> int | None:
    # 计数字段可能是数字或数字字符串,两种都收;其余形态一律不进 metrics
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _news_item(v: dict, position: int) -> ListItem:
    chlname = str(v.get("chlname") or "").strip()
    metrics: dict[str, int] = {}
    for source_key, metric_key in (("readCount", "views"), ("commentNum", "comments"), ("shareCount", "shares")):
        value = _count(v.get(source_key))
        if value is not None:
            metrics[metric_key] = value
    return ListItem(
        id=v["id"],
        title=v["title"],
        desc=v.get("abstract"),
        cover=v.get("miniProShareImage"),
        author=v.get("source"),
        hot=v.get("hotEvent", {}).get("hotScore"),
        # 频道名/号名是条目唯一的原生标识
        badges=[{"text": chlname}] if chlname else [],
        metrics=metrics or None,
        sourceRank=_count(v.get("ranking")) or position,
        timestamp=get_time(v.get("timestamp")),
        url=f"https://new.qq.com/rain/a/{v['id']}",
        mobileUrl=f"https://view.inews.qq.com/k/{v['id']}",
    )
