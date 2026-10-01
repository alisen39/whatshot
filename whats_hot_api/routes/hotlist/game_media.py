from __future__ import annotations

import httpx
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "game-media"

type_map: dict[str, str] = {"gcores-latest": "机核 · 全站最新（官方 RSS）"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "游戏媒体与平台",
    "description": "机核全站最新（官方 RSS：资讯、文章、电台）。",
    "link": "https://www.gcores.com/",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}

FEED_URL = "https://www.gcores.com/rss"
# 如实用程序 UA:/rss 前面的阿里云 WAF 只对冒充浏览器的请求出 JS 挑战页,
# 程序 UA 反而直接给数据(证据 verify/checks.md);拿到挑战页时报错,不执行挑战
PROGRAM_UA = f"python-httpx/{httpx.__version__}"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "gcores-latest")
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    result = await get(
        url=FEED_URL,
        headers={"User-Agent": PROGRAM_UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*"},
        no_cache=no_cache,
        response_type="text",
    )
    body = str(result.data)
    if "aliyun_waf" in body[:2000]:
        raise RuntimeError(
            f"gcores RSS returned an Aliyun WAF challenge page (HTTP body {len(body)} bytes); "
            "challenge is not executed by design"
        )
    items = parse_feed(body)  # 保留 feed 原顺序(原站顺序)
    if not items:
        raise RuntimeError("gcores RSS produced no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[board],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
