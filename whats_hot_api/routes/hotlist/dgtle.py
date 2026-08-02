from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "dgtle"

ROUTE_META: dict = {
    "name": "dgtle",
    "title": "数字尾巴",
    "description": "致力于分享美好数字生活体验，囊括你闻所未闻的最丰富数码资讯，触所未触最抢鲜产品评测，随时随地感受尾巴们各式数字生活精彩图文、摄影感悟、旅行游记、爱物分享。",
    "link": "https://www.dgtle.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    url = "https://opser.api.dgtle.com/v2/news/index"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("items", [])
    data = [
        ListItem(
            id=v["id"],
            title=v.get("title") or v.get("content", ""),
            desc=v.get("content"),
            cover=v.get("cover"),
            author=v.get("from"),
            hot=v.get("membernum"),
            timestamp=get_time(v.get("created_at")),
            url=f"https://www.dgtle.com/news-{v['id']}-{v.get('type', '')}.html",
            mobileUrl=f"https://m.dgtle.com/news-details/{v['id']}",
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
