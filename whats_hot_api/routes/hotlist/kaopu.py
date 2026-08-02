from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "kaopu"
SOURCE_LINK = "https://kaopu.news/"
_URL = "https://kaopustorage.blob.core.windows.net/news-prod/news_list_hans_0.json"
ROUTE_META = {"name": ROUTE_NAME, "title": "靠谱新闻", "description": "靠谱新闻中文精选资讯", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url=_URL, no_cache=no_cache, response_type="json", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    data = [ListItem(id=row.get("link"), title=row.get("title"), desc=row.get("description") or None, author=row.get("publisher") or None, timestamp=get_time(row.get("pub_date")), url=row.get("link"), mobileUrl=row.get("link")) for row in (result.data or []) if row.get("publisher") not in {"财新", "公视"} and row.get("title") and str(row.get("link") or "").startswith("http")]
    return RouterData(**ROUTE_META, type="精选新闻", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
