from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "hupu"

type_map: dict[str, str] = {
    "1": "主干道",
    "6": "恋爱区",
    "11": "校园区",
    "12": "历史区",
    "612": "摄影区",
    "home": "首页热门",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "虎扑",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://bbs.hupu.com/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "1")
    selected_type = type_param if type_param in type_map else "1"
    list_data = (
        await _get_home(no_cache)
        if selected_type == "home"
        else await _get_topic(selected_type, no_cache)
    )
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_topic(topic_id: str, no_cache: bool) -> dict:
    result = await get(
        url="https://m.hupu.com/api/v2/bbs/topicThreads",
        params={"topicId": topic_id, "page": "1"},
        no_cache=no_cache,
    )
    items = result.data.get("data", {}).get("topicThreads", [])
    data = [
        ListItem(
            id=item["tid"],
            title=item["title"],
            author=item.get("username"),
            hot=item.get("replies"),
            url=f"https://bbs.hupu.com/{item['tid']}.html",
            mobileUrl=item.get("url", f"https://bbs.hupu.com/{item['tid']}.html"),
        )
        for item in items
    ]
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_home(no_cache: bool) -> dict:
    result = await get(
        url="https://bbs.hupu.com/",
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        },
    )
    soup = BeautifulSoup(result.data, "html.parser")
    data: list[ListItem] = []
    for info in soup.select(".t-info"):
        anchor = info.select_one("a[href]")
        href = str(anchor.get("href") or "") if anchor else ""
        match = re.fullmatch(r"/(\d{9})\.html", href)
        title_element = info.select_one(".t-title")
        title = title_element.get_text(" ", strip=True) if title_element else ""
        if match is None or not title:
            continue
        thread_id = match.group(1)
        label = info.parent.select_one(".t-label a") if info.parent else None
        lights = _count(info.select_one(".t-lights"))
        replies = _count(info.select_one(".t-replies"))
        item_url = f"https://bbs.hupu.com/{thread_id}.html"
        data.append(
            ListItem(
                id=thread_id,
                title=title,
                desc=(
                    " · ".join(
                        part
                        for part in [
                            label.get_text(" ", strip=True) if label else None,
                            f"{lights} 亮" if lights is not None else None,
                            f"{replies} 回复" if replies is not None else None,
                        ]
                        if part
                    )
                    or None
                ),
                hot=lights if lights is not None else replies,
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _count(element) -> int | None:  # noqa: ANN001
    if element is None:
        return None
    match = re.search(r"([\d.]+)\s*(万)?", element.get_text(" ", strip=True))
    if match is None:
        return None
    value = float(match.group(1))
    return round(value * 10000 if match.group(2) else value)
