from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "acfun"

type_map: dict[str, str] = {
    "-1": "综合",
    "155": "番剧",
    "1": "动画",
    "60": "娱乐",
    "201": "生活",
    "58": "音乐",
    "123": "舞蹈·偶像",
    "59": "游戏",
    "70": "科技",
    "68": "影视",
    "69": "体育",
    "125": "鱼塘",
}

range_map: dict[str, str] = {
    "DAY": "今日",
    "THREE_DAYS": "三日",
    "WEEK": "本周",
}

ROUTE_META: dict = {
    "name": "acfun",
    "title": "AcFun",
    "description": "AcFun是一家弹幕视频网站，致力于为每一个人带来欢乐。",
    "params": {
        "type": {
            "name": "频道",
            "type": type_map,
        },
        "range": {
            "name": "时间",
            "type": range_map,
        },
    },
    "link": "https://www.acfun.cn/rank/list/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "-1")
    range_param = request.query_params.get("range", "DAY")
    list_data = await _get_list(type_param, range_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=f"排行榜 · {type_map.get(type_param, '综合')}",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, range_param: str, no_cache: bool) -> dict:
    channel_id = "" if type_param == "-1" else type_param
    url = f"https://www.acfun.cn/rest/pc-direct/rank/channel?channelId={channel_id}&rankLimit=30&rankPeriod={range_param}"
    result = await get(
        url,
        headers={
            "Referer": f"https://www.acfun.cn/rank/list/?cid=-1&pcid={type_param}&range={range_param}",
        },
        no_cache=no_cache,
    )
    items = result.data["rankList"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [
            ListItem(
                id=v["dougaId"],
                title=v["contentTitle"],
                desc=v.get("contentDesc"),
                cover=v.get("coverUrl"),
                author=v.get("userName"),
                timestamp=get_time(v.get("contributeTime")),
                hot=v.get("likeCount"),
                url=f"https://www.acfun.cn/v/ac{v['dougaId']}",
                mobileUrl=f"https://m.acfun.cn/v/?ac={v['dougaId']}",
            )
            for v in items
        ],
    }
