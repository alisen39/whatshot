from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bbc-news"
type_map = {
    "news": "头条", "world": "国际", "business": "商业", "politics": "政治",
    "health": "健康", "education": "教育", "science-and-environment": "科学与环境",
    "technology": "科技", "entertainment-and-arts": "文化娱乐",
}
ROUTE_META = {"name": ROUTE_NAME, "title": "BBC News", "description": "BBC 官方 RSS 新闻", "link": "https://www.bbc.com/news", "params": {"type": {"name": "栏目", "type": type_map}}}

_FEED_PATHS = {
    'news': '',
    'world': 'world/',
    'business': 'business/',
    'politics': 'politics/',
    'health': 'health/',
    'education': 'education/',
    'science-and-environment': 'science_and_environment/',
    'technology': 'technology/',
    'entertainment-and-arts': 'entertainment_and_arts/',
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get('type', 'news')
    selected = requested if requested in type_map else 'news'
    result = await get(url=f"https://feeds.bbci.co.uk/news/{_FEED_PATHS[selected]}rss.xml", no_cache=no_cache, response_type="text", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,application/xml,text/xml"})
    list_data = {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_feed(result.data)}
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data['data']),
        fromCache=list_data['from_cache'],
        updateTime=list_data['update_time'],
        data=list_data['data'],
    )
