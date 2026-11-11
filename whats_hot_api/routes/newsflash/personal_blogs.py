"""个人博客，每位作者是 ``type=<key>``（2026-11-12 由 9 个热榜路由合并而来）。

读作者自己的 RSS/Atom。Dario Amodei 的网站没有 feed，经 Google News 按站点搜索；
Latent Space 已不在 Substack（自建 feed，2026-11-12 核对），归在这里。
"""

from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import ACCOUNT_FEED_BACKFILL, fetch_account_feed

ROUTE_NAME = "personal-blogs"

# key → (名称, 主页, feed 地址)。第一个是默认作者；新作者加在末尾，并加进 Cloud pj_07/services/board_intervals.py。
BLOGS: dict[str, tuple[str, str, str]] = {
    "sam-altman": ("Sam Altman", "https://blog.samaltman.com/", "https://blog.samaltman.com/posts.atom"),
    "dario-amodei": (
        "Dario Amodei",
        "https://darioamodei.com/",
        "https://news.google.com/rss/search?q=site%3Adarioamodei.com%20Dario%20Amodei&hl=en-US&gl=US&ceid=US%3Aen",
    ),
    "karpathy": ("Andrej Karpathy", "https://karpathy.github.io/", "https://karpathy.github.io/feed.xml"),
    "lilian-weng": ("Lil'Log (Lilian Weng)", "https://lilianweng.github.io/", "https://lilianweng.github.io/index.xml"),
    "simon-willison": ("Simon Willison", "https://simonwillison.net/", "https://simonwillison.net/atom/everything/"),
    "tomer-tunguz": ("Tomer Tunguz", "https://tomtunguz.com/", "https://tomtunguz.com/index.xml"),
    "ruanyifeng": ("阮一峰的网络日志", "https://www.ruanyifeng.com/blog/", "https://www.ruanyifeng.com/blog/atom.xml"),
    "daring-fireball": ("Daring Fireball", "https://daringfireball.net/", "https://daringfireball.net/feeds/main"),
    "latent-space": ("Latent Space", "https://latent.space/", "https://latent.space/feed"),
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "个人博客",
    "description": "AI 与科技领域个人作者博客的最新文章。",
    "params": {"type": {"name": "作者", "type": {key: value[0] for key, value in BLOGS.items()}}},
}

BACKFILL = ACCOUNT_FEED_BACKFILL

__all__ = ["BACKFILL", "ROUTE_META", "ROUTE_NAME", "handle_route"]


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    account = request.query_params.get("type", next(iter(BLOGS)))
    return await fetch_account_feed(ROUTE_META, BLOGS, account, no_cache)
