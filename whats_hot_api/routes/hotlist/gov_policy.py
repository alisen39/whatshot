from __future__ import annotations

import html
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "gov-policy"
SOURCE_LINK = "https://www.gov.cn/zhengce/zhengceku/"
ROUTE_META = {
    "name": ROUTE_NAME,
    "title": "中国政府网",
    "description": "国务院政策文件库最新发布",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新政策",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://sousuo.www.gov.cn/search-gov/data",
        no_cache=no_cache,
        response_type="json",
        params={
            "t": "zhengcelibrary_gw",
            "sort": "publishDate",
            "sortType": "1",
            "pageSize": "30",
            "pageNum": "0",
        },
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    rows = (((result.data or {}).get("searchVO") or {}).get("listVO") or [])
    data = [_policy_item(row) for row in rows]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for item in data if item is not None],
    }


def _policy_item(row: dict) -> ListItem | None:
    policy_id = str(row.get("id") or "").strip()
    title = _clean_text(row.get("title"))
    url = str(row.get("url") or "").strip()
    if not policy_id or not title or not url.startswith("https://www.gov.cn/"):
        return None
    summary = _clean_text(row.get("summary"))
    document_number = _clean_text(row.get("pcode"))
    child_type = _clean_text(row.get("childtype"))
    desc = " · ".join(
        part for part in (document_number, child_type, summary) if part
    )
    return ListItem(
        id=policy_id,
        title=title,
        author=_clean_text(row.get("puborg")) or None,
        desc=desc[:500] or None,
        timestamp=get_time(row.get("pubtime") or row.get("ptime")),
        url=url,
        mobileUrl=url,
    )


def _clean_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
