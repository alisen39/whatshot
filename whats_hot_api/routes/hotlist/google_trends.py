from __future__ import annotations

from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "google-trends"

type_map: dict[str, str] = {
    "US": "美国每日趋势",
    "JP": "日本每日趋势",
    "GB": "英国每日趋势",
    "TW": "台湾每日趋势",
    "IN": "印度每日趋势",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Google Trends",
    "description": "Google Trends 各地区每日热门搜索",
    "params": {
        "type": {
            "name": "地区",
            "type": type_map,
        },
    },
    "link": "https://trends.google.com/trending",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "US")
    selected_type = type_param if type_param in type_map else "US"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(region: str, no_cache: bool) -> dict:
    result = await get(
        url="https://trends.google.com/trending/rss",
        params={"geo": region},
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "User-Agent": "Mozilla/5.0",
        },
    )
    soup = BeautifulSoup(result.data, "xml")
    data: list[ListItem] = []
    for node in soup.find_all("item"):
        title = _tag_text(node, "title")
        published = _tag_text(node, "pubDate")
        if not title:
            continue
        traffic = _tag_text(node, "ht:approx_traffic")
        news_titles = [
            tag.get_text(" ", strip=True)
            for tag in node.find_all("ht:news_item_title")[:3]
            if tag.get_text(" ", strip=True)
        ]
        item_url = (
            "https://trends.google.com/trends/explore?"
            f"geo={region}&q={quote(title)}"
        )
        data.append(
            ListItem(
                id=f"{region}:{published}:{title}",
                title=title,
                desc="；".join(news_titles) or None,
                author=_tag_text(node, "ht:picture_source") or None,
                cover=_tag_text(node, "ht:picture") or None,
                hot=_traffic_number(traffic),
                timestamp=get_time(published),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _tag_text(node, name: str) -> str:  # noqa: ANN001
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _traffic_number(value: str) -> int | None:
    digits = "".join(character for character in value if character.isdigit())
    return int(digits) if digits else None
