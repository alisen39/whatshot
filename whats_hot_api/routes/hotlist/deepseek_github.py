from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'deepseek-github'
SOURCE_LINK = 'https://api-docs.deepseek.com/news/news0725/'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'DeepSeek News',
    "description": 'Official DeepSeek model and API release notes.',
    "link": SOURCE_LINK,
}
# Every news page carries the full news sidebar ("Title YYYY/MM/DD"); the first post's URL is stable.
_ENTRY = re.compile(r'href="(/news/news\d+)/?"[^>]*>([^<]+)<')
_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})\s*$")
_CST = timezone(timedelta(hours=8))


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="News",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # The Google News query this replaced returned unrelated coverage; DeepSeek has no RSS.
    result = await get(url=SOURCE_LINK, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_sidebar(result.data)}


def parse_sidebar(html: str) -> list[ListItem]:
    items: dict[str, ListItem] = {}
    for href, label in _ENTRY.findall(html or ""):
        label = html_lib.unescape(label).strip()
        date = _DATE.search(label)
        if not date or href in items:
            continue
        title = label[:date.start()].strip()
        # Date only, in China time.
        when = datetime(*map(int, date.groups()), tzinfo=_CST)
        url = f"https://api-docs.deepseek.com{href}"
        items[href] = ListItem(id=href.rsplit("/", 1)[-1], title=title, url=url, mobileUrl=url,
                               timestamp=int(when.timestamp() * 1000))
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
