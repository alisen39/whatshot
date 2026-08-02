from __future__ import annotations

import json
from urllib.parse import unquote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_num import parse_chinese_number
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "kuaishou"

APOLLO_STATE_PREFIX = "window.__APOLLO_STATE__="

ROUTE_META: dict = {
    "name": "kuaishou",
    "title": "快手",
    "description": "快手，拥抱每一种生活",
    "link": "https://www.kuaishou.com/",
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
    url = "https://www.kuaishou.com/?isHome=1"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    )

    html = result.data or ""
    start = html.find(APOLLO_STATE_PREFIX)
    if start == -1:
        raise Exception("快手页面结构变更，未找到 APOLLO_STATE")

    script_slice = html[start + len(APOLLO_STATE_PREFIX):]
    sentinel_a = script_slice.find(";(function(")
    sentinel_b = script_slice.find("</script>")

    if sentinel_a != -1 and sentinel_b != -1:
        cut_index = min(sentinel_a, sentinel_b)
    else:
        cut_index = max(sentinel_a, sentinel_b)

    if cut_index == -1:
        raise Exception("快手页面结构变更，未找到 APOLLO_STATE 结束标记")

    raw = script_slice[:cut_index].strip().rstrip(";")

    try:
        last_brace = raw.rfind("}")
        clean_raw = raw[:last_brace + 1] if last_brace != -1 else raw
        json_object = json.loads(clean_raw)["defaultClient"]
    except Exception as err:
        snippet = raw[:200]
        raise Exception(f"快手数据解析失败: {err} | snippet={snippet}...")

    # Get all items from hot rank
    all_items = (
        json_object.get('$ROOT_QUERY.visionHotRank({"page":"home"})', {}).get("items")
        or json_object.get('$ROOT_QUERY.visionHotRank({"page":"home","platform":"web"})', {}).get("items")
        or []
    )

    data: list[ListItem] = []
    for item_ref in all_items:
        item_id = item_ref.get("id", "") if isinstance(item_ref, dict) else ""
        hot_item = json_object.get(item_id)
        if not hot_item:
            continue

        photo_ids = hot_item.get("photoIds", {})
        if isinstance(photo_ids, dict):
            json_ids = photo_ids.get("json", [])
        else:
            json_ids = []
        vid = json_ids[0] if json_ids else ""

        hot_value = hot_item.get("hotValue", "")
        poster = hot_item.get("poster")
        if poster:
            poster = unquote(poster)

        data.append(
            ListItem(
                id=hot_item.get("id", ""),
                title=hot_item.get("name", ""),
                cover=poster,
                hot=parse_chinese_number(str(hot_value)) if hot_value else None,
                url=f"https://www.kuaishou.com/short-video/{vid}",
                mobileUrl=f"https://www.kuaishou.com/short-video/{vid}",
            )
        )

    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}
