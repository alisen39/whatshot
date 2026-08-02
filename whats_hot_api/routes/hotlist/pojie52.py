from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "52pojie"

_TYPE_MAP: dict[str, str] = {
    "digest": "最新精华",
    "hot": "最新热门",
    "new": "最新回复",
    "newthread": "最新发表",
}

ROUTE_META: dict = {
    "name": "52pojie",
    "title": "吾爱破解",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": _TYPE_MAP,
        },
    },
    "link": "https://www.52pojie.cn/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "digest")
    url = f"https://www.52pojie.cn/forum.php?mod=guide&view={type_param}&rss=1"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="arraybuffer",
        headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        },
    )
    # Decode from GBK to UTF-8
    raw_bytes: bytes = result.data
    utf8_data = raw_bytes.decode("gbk", errors="replace")
    data = parse_feed(utf8_data)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP.get(type_param, "最新精华"),
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
