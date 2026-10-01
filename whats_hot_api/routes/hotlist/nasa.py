"""NASA(nasa.gov 官方 RSS:News 最新文章、Image of the Day 每日一图)。

board_api 单元 ``tmp/board_api/nasa`` 的 1:1 迁移,证据见该目录 README 与 ``verify/``。
2 个子榜,每个子榜每次运行 1 个请求,不需要任何请求头(board_api header_matrix:
无 UA、curl、httpx 默认 UA 都返回 200 且条数相同):

- news:https://www.nasa.gov/feed/,全站最新 10 篇(含 science.nasa.gov 的 APOD)
- image-of-the-day:https://www.nasa.gov/feeds/iotd-feed/,NASA Image of the Day,60 条

tophub "NASA 🌍 ‧ 每日星球" 不做:该节点只有 5 条 2023-09 的旧 Image of the Day,条目链到
已下线的旧版接口 /api/2/ubernode/{id}(现 404),现行的同一栏目就是 image-of-the-day。
字段映射与 utils.feed.parse_feed 一致;news 的 cover 为空(feed 没有 media:*/enclosure,
题图只在 content:encoded 正文里);image-of-the-day 的 author 是 feed 的 <source>
"NASA Image of the Day"(parse_feed 按 whatshot 规则回退到 source),不是作者。
"""

from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "nasa"

# 声明序第一个是默认榜(与 board_api DEFAULT_TYPE=news 一致)。
type_map: dict[str, str] = {
    "news": "News",
    "image-of-the-day": "每日一图",
}

FEEDS = {
    "news": "https://www.nasa.gov/feed/",
    "image-of-the-day": "https://www.nasa.gov/feeds/iotd-feed/",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "NASA",
    "description": "NASA 官网最新文章与每日一图（Image of the Day）",
    "link": "https://www.nasa.gov/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in type_map:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")
    result = await get(
        url=FEEDS[selected],
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{selected}",
    )
    items = parse_feed(str(result.data))
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"nasa {selected} feed returned no items ({FEEDS[selected]})")
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
