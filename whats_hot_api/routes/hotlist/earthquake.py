from __future__ import annotations

import json
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "earthquake"

MAPPINGS = {
    "O_TIME": "发震时刻(UTC+8)",
    "LOCATION_C": "参考位置",
    "M": "震级(M)",
    "EPI_LAT": "纬度(°)",
    "EPI_LON": "经度(°)",
    "EPI_DEPTH": "深度(千米)",
    "SAVE_TIME": "录入时间",
}

ROUTE_META: dict = {
    "name": "earthquake",
    "title": "中国地震台",
    "link": "https://news.ceic.ac.cn/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="地震速报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://news.ceic.ac.cn/speedsearch.html"
    result = await get(url=url, no_cache=no_cache, response_type="text")
    regex = re.compile(r"const newdata = (\[.*?\]);", re.DOTALL)
    match = regex.search(result.data)
    raw_list: list[dict] = json.loads(match.group(1)) if match and match.group(1) else []

    data = []
    for v in raw_list:
        new_did = v.get("NEW_DID", "")
        location = v.get("LOCATION_C", "")
        magnitude = v.get("M", "")
        content_parts = [f"{label}：{v.get(key, '')}" for key, label in MAPPINGS.items()]
        data.append(
            ListItem(
                id=new_did,
                title=f"{location}发生{magnitude}级地震",
                desc="\n".join(content_parts),
                timestamp=get_time(v.get("O_TIME", "")),
                url=f"https://news.ceic.ac.cn/{new_did}.html",
                mobileUrl=f"https://news.ceic.ac.cn/{new_did}.html",
            )
        )

    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
