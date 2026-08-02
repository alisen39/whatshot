from __future__ import annotations

from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "gov-law"

SOURCE_LINK = "https://flk.npc.gov.cn/"
_API_URL = "https://flk.npc.gov.cn/law-search/search/list"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "国家法律法规数据库",
    "description": "全国人大常委会办公厅维护的国家法律法规数据库最新公布条目",
    "link": SOURCE_LINK,
}

_STATUS_LABELS = {
    1: "已废止",
    2: "已修改",
    3: "有效",
    4: "尚未生效",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新法律法规",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await post(
        url=_API_URL,
        body={
            "searchRange": 1,
            "sxrq": [],
            "gbrq": [],
            "searchType": 2,
            "sxx": [],
            "gbrqYear": [],
            "flfgCodeId": [],
            "zdjgCodeId": [],
            "searchContent": "",
            "orderByParam": {"order": "gbrq", "sort": "DESC"},
            "pageNum": 1,
            "pageSize": 30,
        },
        no_cache=no_cache,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json;charset=utf-8",
            "Referer": "https://flk.npc.gov.cn/search",
        },
        cache_key="gov-law:recent:gbrq-desc:30",
    )

    payload = result.data or {}
    rows = payload.get("rows") if payload.get("code") == 200 else []
    rows = sorted(
        rows or [],
        key=lambda row: str(row.get("gbrq") or ""),
        reverse=True,
    )
    data = [_law_item(row) for row in rows]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _law_item(row: dict) -> ListItem | None:
    item_id = str(row.get("bbbs") or "").strip()
    title = _text(row.get("title"))
    publish_date = _text(row.get("gbrq"))
    if not item_id or not title or not publish_date:
        return None

    law_type = _text(row.get("flxz"))
    status = _STATUS_LABELS.get(row.get("sxx"))
    effective_date = _text(row.get("sxrq"))
    desc_parts = [part for part in (law_type, status) if part]
    if effective_date:
        desc_parts.append(f"施行日期：{effective_date}")

    detail_url = _detail_url(item_id, title, law_type)
    return ListItem(
        id=item_id,
        title=title,
        author=_text(row.get("zdjgName")) or None,
        desc=" · ".join(desc_parts) or None,
        timestamp=get_time(publish_date),
        url=detail_url,
        mobileUrl=detail_url,
    )


def _detail_url(item_id: str, title: str, law_type: str) -> str:
    query = {
        "id": item_id,
        "fileId": "",
        "type": "decision" if law_type == "修改、废止的决定" else "",
        "title": title,
    }
    return f"https://flk.npc.gov.cn/detail?{urlencode(query)}"


def _text(value: object) -> str:
    return " ".join(str(value or "").split())
