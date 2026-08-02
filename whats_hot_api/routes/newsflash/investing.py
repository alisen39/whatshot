from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "investing"

type_map: dict[str, str] = {
    "stock": "股票市场",
    "crypto": "加密货币",
    "commodities": "大宗商品",
    "forex": "外汇",
    "economy": "经济",
    "indicators": "经济指标",
}

_FEED_IDS: dict[str, str] = {
    "stock": "news_25",
    "crypto": "news_301",
    "commodities": "news_11",
    "forex": "news_1",
    "economy": "news_14",
    "indicators": "news_95",
}

SOURCE_LINK = "https://www.investing.com/news/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Investing.com",
    "description": "Investing.com 全球财经新闻",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "新闻分类",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "stock")
    selected_type = requested_type if requested_type in type_map else "stock"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(selected_type: str, no_cache: bool) -> dict:
    feed_id = _FEED_IDS[selected_type]
    url = f"https://www.investing.com/rss/{feed_id}.rss"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SOURCE_LINK,
        },
    )

    items = parse_feed(result.data)
    data: list[NewsFlashItem] = []
    for item in items:
        title = item.title
        detail_url = item.url
        if not title or not detail_url:
            continue
        data.append(
            NewsFlashItem(
                id=item.id,
                title=title,
                content=title,
                contentStatus="summary",
                source=item.author or "Investing.com",
                tags=[type_map[selected_type]],
                timestamp=item.timestamp,
                url=detail_url,
                mobileUrl=item.mobileUrl,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
