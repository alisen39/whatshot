from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "xueqiu-hotstock"
SOURCE_LINK = "https://xueqiu.com/hq"
ROUTE_META = {"name": ROUTE_NAME, "title": "雪球 · 热门股票", "description": "雪球热门股票榜", "link": SOURCE_LINK}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(url="https://stock.xueqiu.com/v5/stock/hot_stock/list.json", params={"size": "30", "_type": "10", "type": "10"}, no_cache=no_cache, response_type="json", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": SOURCE_LINK})
    data = [ListItem(id=row["code"], title=row.get("name") or row["code"], hot=row.get("percent"), desc=row.get("exchange") or None, url=f"https://xueqiu.com/s/{row['code']}", mobileUrl=f"https://xueqiu.com/s/{row['code']}") for row in ((result.data or {}).get("data") or {}).get("items") or [] if row.get("code") and not row.get("ad")]
    return RouterData(**ROUTE_META, type="热门股票", total=len(data), fromCache=result.from_cache, updateTime=result.update_time, data=data)
