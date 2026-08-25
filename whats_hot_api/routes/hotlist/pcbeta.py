from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "pcbeta"

SOURCE_LINK = "https://bbs.pcbeta.com/"

list_type: dict[str, dict[str, str]] = {
    "windows11": {"name": "Windows 11", "fid": "563"},
    "windows": {"name": "Windows", "fid": "548"},
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "远景论坛",
    "description": "远景论坛 Windows 板块最新主题",
    "params": {
        "type": {
            "name": "板块",
            "type": {key: value["name"] for key, value in list_type.items()},
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "windows11")
    type_info = list_type.get(type_param, list_type["windows11"])
    list_data = await _get_list(type_param, no_cache)
    return RouterData(
        **{**ROUTE_META, "type": type_info["name"]},
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(type_param: str, no_cache: bool) -> dict:
    type_info = list_type.get(type_param, list_type["windows11"])
    result = await get(
        url="https://bbs.pcbeta.com/forum.php",
        params={"mod": "rss", "fid": type_info["fid"]},
        no_cache=no_cache,
        response_type="text",
        headers={"Cookie": "access_js_verified=1"},
    )

    data: list[ListItem] = []
    root = ET.fromstring(result.data)
    for item in root.findall("./channel/item"):
        title = _xml_text(item, "title")
        item_url = _xml_text(item, "link")
        if not title or not item_url:
            continue
        data.append(
            ListItem(
                id=_thread_id(item_url) or item_url,
                title=title,
                author=_xml_text(item, "author") or None,
                desc=_strip_desc(_xml_text(item, "description")) or None,
                timestamp=_rfc822_ms(_xml_text(item, "pubDate")),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _xml_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _thread_id(url: str) -> str | None:
    match = re.search(r"(?:thread|viewthread)-(\d+)-", url)
    return match.group(1) if match else None


def _strip_desc(value: str) -> str:
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
