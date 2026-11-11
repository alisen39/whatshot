"""Substack 上的 Newsletter，每个号是 ``type=<key>``（2026-11-12 由 5 个热榜路由合并而来）。

不同于热榜路由 ``substack``（Substack 官方上升榜）。feed 的 ``<generator>`` 是 Substack，
有的用自定义域名。Latent Space 已不在 Substack（自建 feed），放在 ``personal-blogs``。
"""

from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import ACCOUNT_FEED_BACKFILL, fetch_account_feed

ROUTE_NAME = "substack-newsletters"

# key → (名称, 主页, feed 地址)。第一个是默认号；新号加在末尾，并加进 Cloud pj_07/services/board_intervals.py。
NEWSLETTERS: dict[str, tuple[str, str, str]] = {
    "gary-marcus": ("Gary Marcus", "https://garymarcus.substack.com/", "https://garymarcus.substack.com/feed"),
    "ahead-of-ai": ("Ahead of AI", "https://magazine.sebastianraschka.com/", "https://magazine.sebastianraschka.com/feed"),
    "dwarkesh-patel": ("Dwarkesh Patel", "https://www.dwarkesh.com/", "https://www.dwarkesh.com/feed"),
    "one-useful-thing": ("One Useful Thing", "https://www.oneusefulthing.org/", "https://www.oneusefulthing.org/feed"),
    "interconnects": ("Interconnects", "https://www.interconnects.ai/", "https://www.interconnects.ai/feed"),
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Substack Newsletter",
    "description": "Substack 上的 AI 与科技 Newsletter 最新文章。",
    "link": "https://substack.com/",
    "params": {"type": {"name": "Newsletter", "type": {key: value[0] for key, value in NEWSLETTERS.items()}}},
}

BACKFILL = ACCOUNT_FEED_BACKFILL

__all__ = ["BACKFILL", "ROUTE_META", "ROUTE_NAME", "handle_route"]


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    account = request.query_params.get("type", next(iter(NEWSLETTERS)))
    return await fetch_account_feed(ROUTE_META, NEWSLETTERS, account, no_cache)
