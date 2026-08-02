from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "miit-policy"
SOURCE_LINK = "https://www.miit.gov.cn/zwgk/zcjd/index.html"
API_URL = (
    "https://www.miit.gov.cn/api-gateway/"
    "jpaas-publish-server/front/page/build/unit"
)
API_PARAMS = {
    "parseType": "buildstatic",
    "webId": "8d828e408d90447786ddbe128d495e9e",
    "tplSetId": "209741b2109044b5b7695700b2bec37e",
    "pageType": "column",
    "tagId": "右侧内容",
    "editType": "null",
    "pageId": "1b56e5adc362428299dfc3eb444fe23a",
}
ROUTE_META = {
    "name": ROUTE_NAME,
    "title": "工业和信息化部",
    "description": "工业和信息化部最新政策解读",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="政策解读",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    try:
        result = await _fetch_api(no_cache)
    except Exception:  # The API requires the long-lived cookie set by its column page.
        await get(
            url=SOURCE_LINK,
            no_cache=True,
            response_type="text",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        )
        result = await _fetch_api(no_cache)
    api_data = result.data or {}
    fragment = ((api_data.get("data") or {}).get("html") or "")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_items(fragment),
    }


async def _fetch_api(no_cache: bool):
    return await get(
        url=API_URL,
        no_cache=no_cache,
        response_type="json",
        params=API_PARAMS,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
            "X-Requested-With": "XMLHttpRequest",
        },
    )


def _parse_items(fragment: str) -> list[ListItem]:
    soup = BeautifulSoup(fragment, "lxml")
    data: list[ListItem] = []
    seen: set[str] = set()
    for node in soup.select(".page-content > ul > li"):
        link = node.select_one(":scope > a.fl[href][title]")
        date_node = node.select_one(":scope > span.fr")
        if link is None or date_node is None:
            continue
        href = str(link.get("href") or "").strip()
        title = str(link.get("title") or "").strip()
        match = re.search(r"art_([0-9a-f]+)\.html", href)
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", date_node.get_text(" ", strip=True))
        if not match or not title or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        url = urljoin(SOURCE_LINK, href)
        data.append(
            ListItem(
                id=match.group(1),
                title=title,
                author="工业和信息化部",
                timestamp=get_time(date_match.group(0) if date_match else None),
                url=url,
                mobileUrl=url,
            )
        )
    return data
