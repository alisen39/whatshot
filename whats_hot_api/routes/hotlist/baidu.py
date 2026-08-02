from __future__ import annotations

import json
import re
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "baidu"

type_map: dict[str, str] = {
    "realtime": "热搜",
    "novel": "小说",
    "movie": "电影",
    "teleplay": "电视剧",
    "car": "汽车",
    "game": "游戏",
}

ROUTE_META: dict = {
    "name": "baidu",
    "title": "百度",
    "params": {
        "type": {
            "name": "热搜类别",
            "type": type_map,
        },
    },
    "link": "https://top.baidu.com/board",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "realtime")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map.get(type_param, "热搜"),
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    url = f"https://top.baidu.com/board?tab={type_param}"
    result = await get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        },
        no_cache=no_cache,
        response_type="text",
    )

    # Extract JSON from <!--s-data:...--> comment
    pattern = re.compile(r"<!--s-data:(.*?)-->", re.DOTALL)
    match = pattern.search(result.data)
    if not match:
        return {
            "from_cache": result.from_cache,
            "update_time": result.update_time,
            "data": [],
        }

    json_object: list[dict] = []
    try:
        s_data = json.loads(match.group(1))
        cards = None
        if isinstance(s_data.get("data"), dict):
            cards_list = s_data["data"].get("cards", [])
            if cards_list:
                cards = cards_list[0].get("content")
        if cards is None:
            cards_list = s_data.get("cards", [])
            if cards_list:
                cards = cards_list[0].get("content")

        if isinstance(cards, list):
            if len(cards) > 0 and isinstance(cards[0].get("content"), list):
                json_object = cards[0]["content"]
            else:
                json_object = cards
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        json_object = []

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v.get("index", idx + 1),
                title=v.get("word") or v.get("title") or "",
                desc=v.get("desc") or "",
                cover=v.get("img") or (v.get("imgInfo") or {}).get("src") or "",
                author=", ".join(v["show"]) if isinstance(v.get("show"), list) else (v.get("show") or ""),
                timestamp=0,
                hot=_parse_hot(v.get("hotScore") or v.get("hotTag") or "0"),
                url=f"https://www.baidu.com/s?wd={quote(v.get('query') or v.get('word') or v.get('title') or '')}",
                mobileUrl=v.get("rawUrl") or v.get("url") or "",
            )
            for idx, v in enumerate(json_object)
        ],
    }


def _parse_hot(value: str | int) -> int:
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return 0
