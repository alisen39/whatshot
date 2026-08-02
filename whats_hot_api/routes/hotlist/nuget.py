from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "nuget"

type_map: dict[str, str] = {
    "downloads": "累计下载",
    "recent": "最近更新",
    "six-weeks": "近六周下载",
    "community-six-weeks": "近六周社区下载",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "NuGet",
    "description": "NuGet.org .NET 软件包下载与更新榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://www.nuget.org/packages",
}

_BASE_URL = "https://www.nuget.org"
_SEARCH_URLS = {
    "downloads": f"{_BASE_URL}/packages?sortby=totalDownloads-desc",
    "recent": f"{_BASE_URL}/packages?sortby=created-desc",
}
_STATS_URL = f"{_BASE_URL}/stats/packages"
_DOWNLOAD_RE = re.compile(r"([\d,]+)\s+total downloads", re.IGNORECASE)
_MAX_SEARCH_ITEMS = 20
_MAX_STATS_ITEMS = 100


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "downloads")
    selected = requested if requested in type_map else "downloads"
    list_data = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    if board_type in _SEARCH_URLS:
        result = await get(
            url=_SEARCH_URLS[board_type],
            no_cache=no_cache,
            response_type="text",
            headers=_html_headers(),
        )
        data = _parse_search_page(result.data or "", board_type)
    else:
        result = await get(
            url=_STATS_URL,
            no_cache=no_cache,
            response_type="text",
            headers=_html_headers(),
        )
        tables = _parse_stats_page(result.data or "")
        index = 1 if board_type == "community-six-weeks" else 0
        data = tables[index] if len(tables) > index else []

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_search_page(html: str, board_type: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in soup.select("li.package"):
        anchor = row.select_one("a.package-title[data-package-id]")
        if anchor is None:
            continue
        package_id = _text(anchor.get("data-package-id"))
        version = _text(anchor.get("data-package-version"))
        item_id = (
            f"{package_id}:{version}"
            if board_type == "recent" and version
            else package_id
        )
        if not package_id or not item_id or item_id in seen_ids:
            continue

        href = _text(anchor.get("href"))
        url = urljoin(_BASE_URL, href) if href else f"{_BASE_URL}/packages/{package_id}"
        text = row.get_text(" ", strip=True)
        match = _DOWNLOAD_RE.search(text)
        downloads = _integer(match.group(1)) if match else None
        time_node = row.select_one("[data-datetime]")
        updated_at = _text(time_node.get("data-datetime")) if time_node else ""
        details = row.select_one(".package-details")
        description = details.get_text(" ", strip=True) if details else ""
        description = re.sub(r"\s*More information\s*$", "", description).strip()
        owners = [
            _text(node.get("data-owner"))
            for node in row.select(".package-by a[data-owner]")
            if _text(node.get("data-owner"))
        ]
        tags = [
            node.get_text(" ", strip=True)
            for node in row.select(".package-tags a")
            if node.get_text(" ", strip=True)
        ]
        cover_node = row.select_one("img.package-icon[src]")
        cover = _text(cover_node.get("src")) if cover_node else ""

        rank = len(data) + 1
        desc_parts = [f"排名：{rank}"]
        if version:
            desc_parts.append(f"版本：{version}")
        if description:
            desc_parts.append(description)
        if downloads is not None:
            desc_parts.append(f"累计下载：{downloads:,}")
        if tags:
            desc_parts.append(f"标签：{', '.join(tags)}")

        seen_ids.add(item_id)
        data.append(
            ListItem(
                id=item_id,
                title=f"{package_id} {version}".strip()
                if board_type == "recent"
                else package_id,
                author=", ".join(owners) or None,
                desc=" · ".join(desc_parts),
                hot=downloads,
                cover=cover or None,
                timestamp=get_time(updated_at) if board_type == "recent" else None,
                url=url,
                mobileUrl=url,
            )
        )
        if len(data) == _MAX_SEARCH_ITEMS:
            break
    return data


def _parse_stats_page(html: str) -> list[list[ListItem]]:
    soup = BeautifulSoup(html, "lxml")
    boards: list[list[ListItem]] = []
    for table in soup.select("table")[:2]:
        data: list[ListItem] = []
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            package_id = cells[1].get_text(" ", strip=True)
            downloads = _integer(cells[2].get_text(" ", strip=True))
            if not package_id or downloads is None:
                continue
            rank = len(data) + 1
            url = f"{_BASE_URL}/packages/{package_id}"
            data.append(
                ListItem(
                    id=package_id,
                    title=package_id,
                    desc=f"近六周排名：{rank} · 下载量：{downloads:,}",
                    hot=downloads,
                    url=url,
                    mobileUrl=url,
                )
            )
            if len(data) == _MAX_STATS_ITEMS:
                break
        if data:
            boards.append(data)
    return boards


def _html_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _integer(value: object) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
