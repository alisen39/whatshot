from __future__ import annotations

import json

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_current_datetime, get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "sina-news"

list_type: dict[str, dict[str, str]] = {
    "1": {"name": "总排行", "www": "news", "params": "www_www_all_suda_suda"},
    "2": {"name": "视频排行", "www": "news", "params": "video_news_all_by_vv"},
    "3": {"name": "图片排行", "www": "news", "params": "total_slide_suda"},
    "4": {"name": "国内新闻", "www": "news", "params": "news_china_suda"},
    "5": {"name": "国际新闻", "www": "news", "params": "news_world_suda"},
    "6": {"name": "社会新闻", "www": "news", "params": "news_society_suda"},
    "7": {"name": "体育新闻", "www": "sports", "params": "sports_suda"},
    "8": {"name": "财经新闻", "www": "finance", "params": "finance_0_suda"},
    "9": {"name": "娱乐新闻", "www": "ent", "params": "ent_suda"},
    "10": {"name": "科技新闻", "www": "tech", "params": "tech_news_suda"},
    "11": {"name": "军事新闻", "www": "news", "params": "news_mil_suda"},
}

ROUTE_META: dict = {
    "name": "sina-news",
    "title": "新浪新闻",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": {k: v["name"] for k, v in list_type.items()},
        },
    },
    "link": "https://sinanews.sina.cn/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "1")
    list_data = await _get_list(type_param, no_cache)
    type_info = list_type.get(type_param, list_type["1"])
    return RouterData(
        **{**ROUTE_META, "type": type_info["name"]},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _parse_data(data: str) -> dict:
    """Parse JSONP-style response: var data = {...};"""
    if not data:
        raise ValueError("Input data is empty or invalid")
    prefix = "var data = "
    if not data.startswith(prefix):
        raise ValueError("Input data does not start with the expected prefix")
    json_string = data[len(prefix):].strip()
    if json_string.endswith(";"):
        json_string = json_string[:-1].strip()
    else:
        raise ValueError("Input data does not end with a semicolon")
    if json_string.startswith("{") and json_string.endswith("}"):
        return json.loads(json_string)
    raise ValueError("Invalid JSON format")


async def _get_list(type_param: str, no_cache: bool) -> dict:
    type_info = list_type.get(type_param, list_type["1"])
    params_str = type_info["params"]
    www = type_info["www"]
    dt = get_current_datetime(pad_zero=True)
    date_str = dt["year"] + dt["month"] + dt["day"]
    url = f"https://top.{www}.sina.com.cn/ws/GetTopDataList.php?top_type=day&top_cat={params_str}&top_time={date_str}&top_show_num=50"
    result = await get(url, no_cache=no_cache, response_type="text")
    parsed = _parse_data(result.data)
    items: list[dict] = parsed.get("data", [])
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v.get("id", ""),
                title=v.get("title", ""),
                author=v.get("media") or None,
                hot=_parse_hot_num(v.get("top_num", "0")),
                timestamp=get_time(f"{v.get('create_date', '')} {v.get('create_time', '')}"),
                url=v.get("url", ""),
                mobileUrl=v.get("url", ""),
            )
            for v in items
        ],
    }


def _parse_hot_num(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except (ValueError, AttributeError):
        return 0
