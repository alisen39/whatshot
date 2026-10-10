from __future__ import annotations

import re

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
    "63": "文章",
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

# AcFun CDN 的 UA 黑名单会 403 掉 httpx 缺省 UA("denied by UA ACL = blacklist"),
# 浏览器 UA 直接过,不带 cookie、不需要 Referer
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

_TAG_RE = re.compile(r"<[^>]+>")


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
            **_HEADERS,
            "Referer": f"https://www.acfun.cn/rank/list/?cid=-1&pcid={type_param}&range={range_param}",
        },
        no_cache=no_cache,
    )
    items = result.data["rankList"]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
            "data": [_build_item(v, position) for position, v in enumerate(items, start=1)],
    }


def _build_item(v: dict, position: int) -> ListItem:
    # 文章条目没有 dougaId/likeCount,用 contentId 拼 /a/ac 链接、viewCount 作热度(页面卡片显示的阅读数)
    is_article = not v.get("dougaId")
    ac_id = v.get("contentId") if is_article else v["dougaId"]
    desc = v.get("contentDesc")
    if is_article and desc:
        desc = _TAG_RE.sub("", desc).strip()
    metrics: dict[str, int] = {}
    for key in ("viewCount", "likeCount", "commentCount", "danmakuCount", "shareCount", "stowCount", "bananaCount"):
        value = v.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            metrics[key] = value
    duration_ms = v.get("durationMillis")
    tags = [
        {"text": str(tag.get("name")).strip()}
        for tag in v.get("tagList") or []
        if isinstance(tag, dict) and str(tag.get("name") or "").strip()
    ]
    return ListItem(
        id=ac_id,
        title=v["contentTitle"],
        desc=desc,
        cover=v.get("coverUrl"),
        author=v.get("userName"),
        timestamp=get_time(v.get("contributeTime")),
        hot=v.get("viewCount") if is_article else v.get("likeCount"),
        hotLabel="阅读" if is_article else "点赞",
        metrics=metrics or None,
        durationSeconds=(duration_ms // 1000) if isinstance(duration_ms, int) and duration_ms > 0 else None,
        badges=tags or [],
        sourceRank=position,
        url=f"https://www.acfun.cn/{'a' if is_article else 'v'}/ac{ac_id}",
        mobileUrl=v.get("shareUrl") or f"https://m.acfun.cn/v/?ac={ac_id}",
    )
