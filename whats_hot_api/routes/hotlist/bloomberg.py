from __future__ import annotations

import asyncio
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.http_client import CacheOnlyMiss

ROUTE_NAME = "bloomberg"
type_map = {"main": "头条", "markets": "市场", "economics": "经济", "industries": "产业", "technology": "科技", "politics": "政治", "opinions": "观点", "crypto": "加密资产", "google": "Google 新闻聚合"}
ROUTE_META = {"name": ROUTE_NAME, "title": "Bloomberg", "description": "Bloomberg 官方栏目与 Google 新闻聚合", "link": "https://www.bloomberg.com/", "params": {"type": {"name": "栏目", "type": type_map}}}

_FEED_URLS = {
    'main': 'https://feeds.bloomberg.com/news.rss',
    'markets': 'https://feeds.bloomberg.com/markets/news.rss',
    'economics': 'https://feeds.bloomberg.com/economics/news.rss',
    'industries': 'https://feeds.bloomberg.com/industries/news.rss',
    'technology': 'https://feeds.bloomberg.com/technology/news.rss',
    'politics': 'https://feeds.bloomberg.com/politics/news.rss',
    'opinions': 'https://feeds.bloomberg.com/bview/news.rss',
    'crypto': 'https://feeds.bloomberg.com/crypto/news.rss',
    'google': (
        'https://news.google.com/rss/search?'
        'q=site%3Abloomberg.com&hl=en-US&gl=US&ceid=US%3Aen'
    ),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get('type', 'main')
    selected = requested if requested in type_map else 'main'
    for attempt in range(3):
        try:
            result = await get(url=_FEED_URLS[selected], no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,application/xml,text/xml"})
            list_data = {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)}
            break
        except CacheOnlyMiss:
            raise
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(0.4 * (attempt + 1))
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data['data']),
        fromCache=list_data['from_cache'],
        updateTime=list_data['update_time'],
        data=list_data['data'],
    )
