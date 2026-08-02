from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger
from whats_hot_api.utils.tokens.bilibili import get_bili_wbi

ROUTE_NAME = "bilibili"

type_map: dict[str, str] = {
    "0": "全站",
    "1": "动画",
    "3": "音乐",
    "4": "游戏",
    "5": "娱乐",
    "188": "科技",
    "119": "鬼畜",
    "129": "舞蹈",
    "155": "时尚",
    "160": "生活",
    "168": "国创相关",
    "181": "影视",
}

ROUTE_META: dict = {
    "name": "bilibili",
    "title": "哔哩哔哩",
    "description": "你所热爱的，就是你的生活",
    "link": "https://www.bilibili.com/v/popular/rank/all",
    "params": {
        "type": {
            "name": "排行榜分区",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "0")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=f"热榜 · {type_map.get(type_param, '全站')}",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    wbi_data = await get_bili_wbi()
    url = f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={type_param}&type=all&{wbi_data}"
    headers = {
        "Referer": "https://www.bilibili.com/ranking/all",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    result = await get(url, headers=headers, no_cache=no_cache)
    data = result.data

    # Check if new API returned data
    if data.get("data", {}).get("list"):
        logger.info("bilibili 新接口")
        items = data["data"]["list"]
        return {
            "from_cache": result.from_cache,
            "update_time": result.update_time,
            "data": [
                ListItem(
                    id=v["bvid"],
                    title=v["title"],
                    desc=v.get("desc") or "该视频暂无简介",
                    cover=(v.get("pic") or "").replace("http:", "https:") or None,
                    author=v.get("owner", {}).get("name"),
                    timestamp=get_time(v.get("pubdate")),
                    hot=v.get("stat", {}).get("view", 0),
                    url=v.get("short_link_v2") or f"https://www.bilibili.com/video/{v['bvid']}",
                    mobileUrl=f"https://m.bilibili.com/video/{v['bvid']}",
                )
                for v in items
            ],
        }

    # Fallback API
    logger.info("bilibili 备用接口")
    fallback_url = f"https://api.bilibili.com/x/web-interface/ranking?jsonp=jsonp?rid={type_param}&type=all&callback=__jp0"
    fallback_headers = {
        "Referer": "https://www.bilibili.com/ranking/all",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    }
    result2 = await get(fallback_url, headers=fallback_headers, no_cache=no_cache)
    items = result2.data["data"]["list"]
    return {
        "from_cache": result2.from_cache,
        "update_time": result2.update_time,
        "data": [
            ListItem(
                id=v["bvid"],
                title=v["title"],
                desc=v.get("desc") or "该视频暂无简介",
                cover=(v.get("pic") or "").replace("http:", "https:") or None,
                author=v.get("author"),
                timestamp=get_time(v.get("pubdate")),
                hot=v.get("video_review"),
                url=f"https://www.bilibili.com/video/{v['bvid']}",
                mobileUrl=f"https://m.bilibili.com/video/{v['bvid']}",
            )
            for v in items
        ],
    }
