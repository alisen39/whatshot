from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "fed-monetary"

# 美联储理事会货币政策类新闻稿(FOMC 声明、会议纪要、经济预测、贴现率会议纪要等),
# 官方 RSS 最新 15 条,更新不频繁。公开 feed,实测无 UA/curl/httpx 默认 UA 均 200,
# Cloudflare 下发的 __cf_bm cookie 不需要带回(header_matrix.jsonl);
# 响应带 UTF-8 BOM,parse_feed 能正常解析。
_FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_ACCEPT = "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"

type_map = {
    "hot": "货币政策新闻稿",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "美联储",
    "description": "美联储理事会货币政策类新闻稿(FOMC 声明、会议纪要、经济预测等)",
    "link": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", "hot")
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    result = await get(
        url=_FEED_URL, headers={"Accept": _ACCEPT}, no_cache=no_cache, response_type="text"
    )
    # parse_feed 按发布时间倒序(稳定排序):feed 本身就是倒序,同一时刻发布的两条
    # (FOMC 声明 …a.htm 与经济预测 …b.htm)保持 feed 原顺序,与原站一致
    items = parse_feed(str(result.data))
    if not items:
        raise RuntimeError("Federal Reserve monetary-policy feed produced no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[board_type],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
