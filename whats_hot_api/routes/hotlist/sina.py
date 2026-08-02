from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_num import parse_chinese_number
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sina"

type_map: dict[str, str] = {
    "all": "新浪热榜",
    "hotcmnt": "热议榜",
    "minivideo": "视频热榜",
    "ent": "娱乐热榜",
    "ai": "AI热榜",
    "auto": "汽车热榜",
    "mother": "育儿热榜",
    "fashion": "时尚热榜",
    "travel": "旅游热榜",
    "esg": "ESG热榜",
}

ROUTE_META: dict = {
    "name": "sina",
    "title": "新浪网",
    "description": "热榜太多，一个就够",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://sinanews.sina.cn/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "all")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "新浪热榜"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://newsapp.sina.cn/api/hotlist?newsId=HB-1-snhs%2Ftop_news_list-{type_param}"
    result = await get(url, no_cache=no_cache)
    items = result.data["data"]["hotList"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["base"]["base"]["uniqueId"],
                title=v["info"]["title"],
                desc=None,
                author=None,
                timestamp=None,
                hot=parse_chinese_number(v["info"].get("hotValue", "0")),
                url=v["base"]["base"]["url"],
                mobileUrl=v["base"]["base"]["url"],
            )
            for v in items
        ],
    }
