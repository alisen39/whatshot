from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "weatheralarm"

ROUTE_META: dict = {
    "name": "weatheralarm",
    "title": "中央气象台",
    "params": {
        "province": {
            "name": "预警区域",
            "value": "省份名称（ 例如：广东省 ）",
        },
    },
    "link": "http://nmc.cn/publish/alarm.html",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    province = request.query_params.get("province", "")
    list_data = await _get_list(province, no_cache)
    return RouterData(
        **ROUTE_META,
        type=f"{province or '全国'}气象预警",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(province: str, no_cache: bool) -> dict:
    url = f"http://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=20&signaltype=&signallevel=&province={quote(province)}"
    result = await get(url=url, no_cache=no_cache)
    items = result.data.get("data", {}).get("page", {}).get("list", [])
    data = [
        ListItem(
            id=v.get("alertid", ""),
            title=v.get("title", ""),
            desc=f"{v.get('issuetime', '')} {v.get('title', '')}",
            cover=v.get("pic") or None,
            timestamp=get_time(v.get("issuetime", "")),
            url=f"http://nmc.cn{v.get('url', '')}",
            mobileUrl=f"http://nmc.cn{v.get('url', '')}",
        )
        for v in items
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
