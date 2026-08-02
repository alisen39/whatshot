from __future__ import annotations

import json

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "qqvideo-tv-hotsearch"

SOURCE_LINK = "https://v.qq.com/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "腾讯视频热搜榜",
    "description": "腾讯视频电视剧热搜榜",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="热搜榜",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = (
        "https://pbaccess.video.qq.com/trpc.vector_layout.page_view.PageService/getCard"
        "?video_appid=3000010&vversion_platform=2"
    )
    result = await post(
        url=url,
        no_cache=no_cache,
        body=_request_body(),
        cache_key=f"{url}&rank=HotSearch",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    cards = (
        (result.data or {})
        .get("data", {})
        .get("card", {})
        .get("children_list", {})
        .get("list", {})
        .get("cards")
        or []
    )
    data: list[ListItem] = []
    for card in cards:
        params = card.get("params") if isinstance(card.get("params"), dict) else {}
        title = (params.get("title") or "").strip()
        cid = params.get("cid") or card.get("id")
        if not title or not cid:
            continue
        url_value = f"https://v.qq.com/x/cover/{cid}.html"
        data.append(
            ListItem(
                id=str(card.get("id") or cid),
                title=title,
                cover=params.get("image_url") or None,
                desc=(
                    params.get("sub_title")
                    or params.get("rec_normal_reason")
                    or ""
                ).strip() or None,
                timestamp=get_time(params.get("publish_date")),
                url=url_value,
                mobileUrl=url_value,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _request_body() -> dict:
    return {
        "page_params": {
            "rank_channel_id": "100113",
            "rank_name": "HotSearch",
            "rank_page_size": "30",
            "tab_mvl_sub_mod_id": "792ac_19e77Sub_1b2",
            "tab_name": "热搜榜",
            "tab_type": "hot_rank",
            "tab_vl_data_src": "f5200deb4596bbf3",
            "page_id": "scms_shake",
            "page_type": "scms_shake",
            "source_key": "",
            "tag_id": "",
            "tag_type": "",
            "new_mark_label_enabled": "1",
        },
        "page_context": {"page_index": "1"},
        "flip_info": {
            "page_strategy_id": "",
            "page_module_id": "792ac_19e77",
            "module_strategy_id": {},
            "sub_module_id": "20251106065177",
            "flip_params": {
                "folding_screen_show_num": "",
                "is_mvl": "1",
                "mvl_strategy_info": json.dumps(
                    {
                        "default_strategy_id": "06755800b45b49238582a6fa1ad0f5c5",
                        "default_version": "3836",
                        "hit_page_uuid": "b5080d97dc694a5fb50eb9e7c99326ac",
                        "hit_tab_info": None,
                        "gray_status_info": None,
                        "bypass_to_un_exp_id": "",
                    },
                    ensure_ascii=False,
                ),
                "mvl_sub_mod_id": "20251106065177",
                "pad_post_show_num": "",
                "pad_pro_post_show_num": "",
                "pad_pro_small_hor_pic_display_num": "",
                "pad_small_hor_pic_display_num": "",
                "page_id": "scms_shake",
                "page_num": "0",
                "page_type": "scms_shake",
                "post_show_num": "",
                "shake_size": "",
                "small_hor_pic_display_num": "",
                "source_key": "100113",
                "un_policy_id": "06755800b45b49238582a6fa1ad0f5c5",
                "un_strategy_id": "06755800b45b49238582a6fa1ad0f5c5",
            },
            "relace_children_key": [],
        },
    }
