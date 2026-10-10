from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zhihu"

ROUTE_META: dict = {
    "name": "zhihu",
    "title": "知乎",
    "link": "https://www.zhihu.com/hot",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://api.zhihu.com/topstory/hot-lists/total?limit=50"
    headers = {}
    if config.ZHIHU_COOKIE:
        headers["Cookie"] = config.ZHIHU_COOKIE
    result = await get(url=url, headers=headers or None, no_cache=no_cache)
    items = result.data.get("data", [])
    if not isinstance(items, list) or not items:
        raise ValueError("Zhihu hot list returned no entries")
    data = []
    for v in items:
        target = v["target"]
        question_id = target["url"].split("/")[-1]
        detail_text = v.get("detail_text", "0 万热度")
        hot_str = detail_text.split(" ")[0]
        try:
            hot = float(hot_str) * 10000
        except (ValueError, TypeError):
            hot = 0
        data.append(
            ListItem(
                id=target["id"],
                title=target["title"],
                desc=target.get("excerpt"),
                cover=v["children"][0]["thumbnail"] if v.get("children") else None,
                timestamp=get_time(target.get("created")),
                hot=hot,
                hotLabel="热度",
                badges=[{"code": v["card_label"].get("type"),
                         "imageUrl": v["card_label"].get("icon"),
                         "darkImageUrl": v["card_label"].get("night_icon"),
                         "text": {"new": "新", "hot": "热"}.get(str(v["card_label"].get("type")))}]
                    if isinstance(v.get("card_label"), dict) else [],
                metrics={key: target[field] for key, field in
                         (("answers", "answer_count"), ("followers", "follower_count")) if field in target},
                url=f"https://www.zhihu.com/question/{question_id}",
                mobileUrl=f"https://www.zhihu.com/question/{question_id}",
            )
        )
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
