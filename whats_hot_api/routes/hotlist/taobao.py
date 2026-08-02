from __future__ import annotations

import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "taobao"

type_map: dict[str, str] = {
    "chuanda": "穿搭",
    "shuma": "数码",
    "lvxing": "旅行",
    "zhichang": "职场",
    "yundong": "运动",
    "jianshen": "健身",
    "meizhuang": "美妆",
    "gonglue": "攻略",
    "xuexi": "学习",
    "qinzi": "亲子",
    "jiaocheng": "教程",
    "muying": "母婴",
    "jiaju": "家居",
    "xiaozhong": "小众",
    "meishi": "美食",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "淘宝逛一逛",
    "description": "淘宝逛一逛官方公开分类主题推荐",
    "params": {
        "type": {
            "name": "主题分类",
            "type": type_map,
        },
    },
    "link": "https://guangtao.taobao.com/",
}

_BASE_URL = "https://guangtao.taobao.com"
_CONTEXT_MARKER = "var b = "
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "chuanda")
    selected_type = type_param if type_param in type_map else "chuanda"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    url = f"{_BASE_URL}/category-{board_type}"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"taobao:guangtao:{board_type}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_board(result.data, board_type),
    }


def _parse_board(html: object, board_type: str) -> list[ListItem]:
    if not isinstance(html, str) or board_type not in type_map:
        return []
    expected_url = f"{_BASE_URL}/category-{board_type}"
    soup = BeautifulSoup(html, "lxml")
    canonical = soup.select_one('link[rel="canonical"]')
    active_tabs = soup.select(".ai-guang-theme-tabs-item-active")
    expected_tab = soup.select_one(f"#theme-tab-{board_type}")
    if (
        canonical is None
        or str(canonical.get("href") or "").rstrip("/") != expected_url
        or len(active_tabs) != 1
        or expected_tab is None
        or active_tabs[0].get("id") != f"theme-tab-{board_type}"
        or expected_tab.get_text(" ", strip=True) != type_map[board_type]
    ):
        return []

    payload = _extract_context(html)
    if (
        not isinstance(payload, dict)
        or payload.get("renderMode") != "SSR"
        or payload.get("routePath") != "/aiGuangHome"
        or payload.get("matchedIds") != ["aiGuangHome"]
    ):
        return []
    try:
        home = payload["loaderData"]["aiGuangHome"]["data"][0]["homePageData"]
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(home, dict) or not _valid_tab_list(home.get("tabList"), board_type):
        return []
    feeds = home.get("feedsList")
    if not isinstance(feeds, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for feed in feeds:
        item = _theme_item(feed)
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _extract_context(html: str) -> object:
    start = html.find(_CONTEXT_MARKER)
    if start < 0:
        return None
    start += len(_CONTEXT_MARKER)
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(html[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : index + 1])
                except json.JSONDecodeError:
                    return None
            if depth < 0:
                return None
    return None


def _valid_tab_list(value: object, board_type: str) -> bool:
    if not isinstance(value, list):
        return False
    tabs: dict[str, str] = {}
    for row in value:
        if not isinstance(row, dict):
            return False
        tab_id = _clean_text(row.get("tabId"))
        tab_name = _clean_text(row.get("tabName"))
        if not tab_id or not tab_name or tab_id in tabs:
            return False
        tabs[tab_id] = tab_name
    return tabs.get("all") == "推荐" and tabs.get(board_type) == type_map[board_type]


def _theme_item(value: object) -> ListItem | None:
    if not isinstance(value, dict):
        return None
    theme_id = _clean_text(value.get("themePageId"))
    title = _clean_text(value.get("floorTitle"))
    if (
        not theme_id.isdigit()
        or int(theme_id) <= 0
        or value.get("selfTheme") is not False
        or value.get("source") != 7
        or not title
        or _clean_text(value.get("title")) != title
    ):
        return None

    desc_parts: list[str] = []
    subtitle = _clean_text(value.get("floorSubTitle"))
    if subtitle:
        desc_parts.append(subtitle)
    keywords = _clean_text(value.get("keywords")).replace(",", "、")
    if keywords:
        desc_parts.append(f"关键词：{keywords}")
    category = _clean_text(value.get("seo_category"))
    if category:
        desc_parts.append(f"类目：{category}")

    url = f"{_BASE_URL}/topic-{theme_id}.html"
    return ListItem(
        id=theme_id,
        title=title,
        desc=" · ".join(desc_parts) or None,
        hot=_positive_int_or_zero(value.get("likeCount")),
        cover=_https_url(value.get("floorPicUrl")),
        url=url,
        mobileUrl=url,
    )


def _positive_int_or_zero(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _https_url(value: object) -> str | None:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return url


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
