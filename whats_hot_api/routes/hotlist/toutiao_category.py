from __future__ import annotations

import json

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "toutiao-category"

type_map: dict[str, str] = {
    "sports": "体育榜",
    "finance": "财经榜",
    "entertainment": "娱乐榜",
    "technology": "科技榜",
    "car": "汽车榜",
    "education": "教育榜",
    "health": "健康榜",
    "international": "国际榜",
    "military": "军事榜",
    "culture": "文旅榜",
    "taiwan": "台海榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "今日头条",
    "description": "今日头条 App 热点频道里的分类热榜(主榜由 toutiao 路由提供)。",
    "link": "https://www.toutiao.com/",
    "params": {
        "type": {
            "name": "分类",
            "type": type_map,
        },
    },
}

_FEED_URL = "https://i-lq.snssdk.com/api/news/feed/v88/"
# "热点"频道(不是 news_hot);分类榜作为一串卡片挂在这个频道的信息流里。
# update_version_code 是真正的门槛:88007+ 才有 12 张卡片,85007- 只有主榜;服务端下线旧版本时会失效
_FEED_PARAMS = {
    "category": "news_hotspot",
    "aid": "13",
    "device_platform": "android",
    "version_code": "950",
    "update_version_code": "95007",
    "channel": "xiaomi",
}
_HEADERS = {"User-Agent": "okhttp/3.10.0.1"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "sports")
    if type_param not in type_map:
        raise ValueError(f"Unknown category '{type_param}' for route '{ROUTE_NAME}'")
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    result = await get(
        url=_FEED_URL,
        params=_FEED_PARAMS,
        no_cache=no_cache,
        response_type="json",
        headers=_HEADERS,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if not payload:
        # 缺 update_version_code 或客户端版本被下线时返回空响应
        raise RuntimeError("Toutiao feed returned an empty response")
    found = _boards(payload)
    board = found.get(type_param)
    if board is None:
        raise RuntimeError(
            f"Toutiao hotspot feed has no '{type_param}' board (got {sorted(found)}); "
            "version_code may be retired or the channel changed"
        )
    data = [
        ListItem(
            id=str(it.get("id_str") or it.get("id")),
            title=it.get("title") or "",
            url=f"https://www.toutiao.com/trending/{it.get('id_str') or it.get('id')}/",
            mobileUrl=f"https://www.toutiao.com/trending/{it.get('id_str') or it.get('id')}/",
        )
        for it in board.get("hot_board_items") or []
        if it.get("id_str") or it.get("id")
    ]
    if not data:
        raise RuntimeError(f"Toutiao '{type_param}' board card contained no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
        "message": None,
    }


def _boards(payload: dict) -> dict[str, dict]:
    """抽出热点频道信息流里 cell_type=800 的热榜卡片,按 board.category 建索引。"""
    out: dict[str, dict] = {}
    for cell in payload.get("data") or []:
        content = cell.get("content")
        try:
            card = json.loads(content) if isinstance(content, str) and content else (content or {})
        except ValueError:
            continue  # 非 JSON 的普通信息流卡片
        if not isinstance(card, dict) or card.get("cell_type") != 800:
            continue
        raw = card.get("raw_data")
        if not isinstance(raw, dict):
            # 上游结构漂移,不是类型契约问题,刻意用 RuntimeError
            raise RuntimeError("Toutiao hot-board card raw_data is not an object (feed changed)")  # noqa: TRY004
        for board in raw.get("board") or []:
            out[board.get("category") or ""] = board
    return out
