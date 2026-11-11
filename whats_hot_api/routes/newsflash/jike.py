"""即刻圈子（m.okjike.com），每个圈子是 ``type=<key>``。2026-11-12 从热榜 ``pro-communities`` 移来。

圈子页 ``/topics/<圈子 id>`` 是 Next.js 服务端渲染，取 ``__NEXT_DATA__.props.pageProps.posts``。
服务端只渲染 10 条，顺序是原站给的精选 / 热门序（不是按时间，board_api 实测），所以按条累积存储时
只能收到进过这 10 条的帖子。圈子 id 由 tophub 条目的帖子页反查（board_api 分析阶段）。
帖子没有标题，取正文第一行非空文字（超 80 字截断加“…”）。
"""

from __future__ import annotations

import json
import re

from starlette.requests import Request

from whats_hot_api.backfill import snapshot
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics

ROUTE_NAME = "jike"

# key → (圈子名, 圈子 id)。第一个是默认圈子；新圈子加在末尾，并加进 Cloud pj_07/services/board_intervals.py。
CIRCLES: dict[str, tuple[str, str]] = {
    "ai-explore": ("AI探索站", "63579abb6724cc583b9bba9a"),
    "pm-daily": ("产品经理的日常", "563a2995306dab1300a32227"),
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "即刻",
    "description": "即刻圈子里的帖子（圈子页的精选、热门帖）。",
    "link": "https://m.okjike.com/",
    "params": {"type": {"name": "圈子", "type": {key: name for key, (name, _id) in CIRCLES.items()}}},
}

BACKFILL = {
    "*": snapshot("圈子页服务端只渲染 10 条精选、热门帖，没有翻页或按时间回溯。", verified_at="2026-11-12"),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TITLE_MAX = 80


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    key = request.query_params.get("type", next(iter(CIRCLES)))
    name, circle_id = CIRCLES[key]
    url = f"https://m.okjike.com/topics/{circle_id}"
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text", cache_key=f"{ROUTE_NAME}:{key}")
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', str(result.data), re.DOTALL)
    posts = json.loads(match.group(1))["props"]["pageProps"].get("posts") if match else None
    if not isinstance(posts, list):
        raise RuntimeError(f"jike topic page {url} has no posts list (page changed)")  # noqa: TRY004

    items: list[NewsFlashItem] = []
    for post in posts:
        post_id = str(post.get("id") or "")
        content = str(post.get("content") or "").strip()
        title = _post_title(content)
        if not post_id or not title:
            continue
        kind = "originalPosts" if post.get("type") in (None, "ORIGINAL_POST") else "reposts"
        post_url = f"https://m.okjike.com/{kind}/{post_id}"
        user = post.get("user") or {}
        items.append(
            NewsFlashItem(
                id=post_id,
                title=title,
                content=content,
                source=user.get("screenName") or name,
                images=[p["picUrl"] for p in post.get("pictures") or [] if p.get("picUrl")],
                metrics=metrics(likes=post.get("likeCount")),
                timestamp=get_time(str(post.get("createdAt") or "")),
                url=post_url,
                mobileUrl=post_url,
            )
        )
    if not items:
        raise RuntimeError(f"jike topic page {url} returned no posts")
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=name,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _post_title(content: str) -> str:
    """帖子没有标题：取正文第一行非空文字，超过 80 字截断加“…”。"""
    first = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return first if len(first) <= _TITLE_MAX else first[:_TITLE_MAX] + "…"
