from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "douyin"

ROUTE_META: dict = {
    "name": "douyin",
    "title": "抖音",
    "description": "实时上升热点",
    "link": "https://www.douyin.com",
}

# 风控口径(board_api 推翻性验证后的结论):
# - 不需要任何 cookie;此前取 cookie 的 login_guiding_strategy 引导接口本身会被风控拦截,
#   导致整个路由失败,已移除。带非空 Referer(任意值)即可拿到完整数据。
# - UA 按子串拉黑(curl/、python-requests、aiohttp 等),用桌面浏览器 UA。
# - a_bogus/msToken 可以不带。
# - version_name 必需:缺失时只回 48~49 条且名次被重排成连续 1..48,与官方错位。
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/hot",
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


async def _get_list(no_cache: bool) -> dict:
    url = (
        "https://www.douyin.com/aweme/v1/web/hot/search/list/"
        "?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1&version_name=17.4.0"
    )
    result = await get(url=url, no_cache=no_cache, headers=_HEADERS)
    word_list = (result.data.get("data") or {}).get("word_list") or []
    if not word_list:
        # UA 被拉黑或缺 Referer 时上游返回 200 空响应,按上游故障处理,不静默降级为空榜
        raise RuntimeError("Douyin hot search list returned no entries (blocked request)")
    data = [
        ListItem(
            id=v.get("sentence_id", ""),
            title=v.get("word", ""),
            desc="置顶" if v.get("word_type") == 14 else None,
            timestamp=get_time(v.get("event_time", "")),
            hot=v.get("hot_value"),
            url=f"https://www.douyin.com/hot/{v.get('sentence_id', '')}",
            mobileUrl=f"https://www.douyin.com/hot/{v.get('sentence_id', '')}",
        )
        for v in word_list
    ]
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
