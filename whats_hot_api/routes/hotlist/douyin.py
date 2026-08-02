from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "douyin"

ROUTE_META: dict = {
    "name": "douyin",
    "title": "抖音",
    "description": "实时上升热点",
    "link": "https://www.douyin.com",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_dy_cookies() -> str | None:
    try:
        cookie_url = "https://www.douyin.com/passport/general/login_guiding_strategy/?aid=6383"
        result = await get(url=cookie_url, origin_info=True)
        headers = result.data.get("headers", {})
        set_cookie = headers.get("set-cookie", "")
        pattern = re.compile(r"passport_csrf_token=(.*?);", re.DOTALL)
        match = pattern.search(set_cookie)
        return match.group(1) if match else None
    except Exception as e:
        logger.error(f"获取抖音 Cookie 出错: {e}")
        return None


async def _get_list(no_cache: bool) -> dict:
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
    cookie = await _get_dy_cookies()
    result = await get(
        url=url,
        no_cache=no_cache,
        headers={"Cookie": f"passport_csrf_token={cookie}"} if cookie else None,
    )
    word_list = result.data.get("data", {}).get("word_list", [])
    data = [
        ListItem(
            id=v.get("sentence_id", ""),
            title=v.get("word", ""),
            timestamp=get_time(v.get("event_time", "")),
            hot=v.get("hot_value"),
            url=f"https://www.douyin.com/hot/{v.get('sentence_id', '')}",
            mobileUrl=f"https://www.douyin.com/hot/{v.get('sentence_id', '')}",
        )
        for v in word_list
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
