from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.nextjs import flight_text, json_values

ROUTE_NAME = 'kimi-updates'
SOURCE_LINK = 'https://www.kimi.com/en/blog/'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Moonshot AI Kimi',
    "description": 'Moonshot AI and Kimi product or model updates.',
    "link": SOURCE_LINK,
}
_CST = timezone(timedelta(hours=8))
# Off-site entries are kept only on Moonshot's own accounts (one links a partner's repo).
_OFFICIAL_PREFIXES = ("https://github.com/MoonshotAI/", "https://huggingface.co/moonshotai/",
                      "https://moonshotai.github.io/")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Blog",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # The research blog embeds its article list in the Next.js payload; no RSS exists.
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_blog(result.data)}


def parse_blog(html: str) -> list[ListItem]:
    items: dict[str, ListItem] = {}
    for block in json_values(flight_text(html), "articleList"):
        for post in (block.get("items") if isinstance(block, dict) else None) or []:
            if not isinstance(post, dict):
                continue
            href, title, date = str(post.get("href") or ""), str(post.get("title") or "").strip(), post.get("date")
            url = f"https://www.kimi.com{href}" if href.startswith("/") else href
            if not title or not (href.startswith("/") or href.startswith(_OFFICIAL_PREFIXES)) or url in items:
                continue
            try:
                timestamp = int(datetime.strptime(str(date), "%Y-%m-%d").replace(tzinfo=_CST).timestamp() * 1000)
            except ValueError:
                continue
            items[url] = ListItem(id=str(post.get("id") or url), title=title, url=url, mobileUrl=url,
                                  desc=post.get("description") or None, timestamp=timestamp,
                                  cover=post.get("image") if str(post.get("image") or "").startswith("https://") else None)
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
