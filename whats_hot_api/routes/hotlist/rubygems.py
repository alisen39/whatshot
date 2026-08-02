from __future__ import annotations

from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "rubygems"

type_map: dict[str, str] = {
    "downloads": "累计下载",
    "latest": "新增 Gem",
    "updated": "最近更新",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "RubyGems",
    "description": "RubyGems.org 下载与发布活动榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://rubygems.org/",
}

_BASE_URL = "https://rubygems.org"
_API_BASE = f"{_BASE_URL}/api/v1"


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
    if board_type == "downloads":
        result = await get(
            url=f"{_BASE_URL}/stats",
            no_cache=no_cache,
            response_type="text",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )
        data = _parse_downloads(result.data or "")
    else:
        activity = "latest" if board_type == "latest" else "just_updated"
        result = await get(
            url=f"{_API_BASE}/activity/{activity}.json",
            no_cache=no_cache,
            response_type="json",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )
        data = _parse_activity(result.data, board_type)

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_downloads(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    heading = next(
        (
            node
            for node in soup.find_all(("h2", "h3"))
            if "All Time Most Downloaded" in node.get_text(" ", strip=True)
        ),
        None,
    )
    article = heading.find_parent("article") if heading else None
    if article is None:
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for anchor in article.select('a[href^="/gems/"]'):
        name = anchor.get_text(" ", strip=True)
        href = str(anchor.get("href") or "").strip()
        block = anchor.find_parent("div")
        count_node = block.select_one('[data-controller="stats"] span') if block else None
        downloads = _integer(count_node.get_text(" ", strip=True) if count_node else "")
        if not name or not href or downloads is None or name in seen_ids:
            continue
        rank = len(data) + 1
        url = urljoin(_BASE_URL, href)
        seen_ids.add(name)
        data.append(
            ListItem(
                id=name,
                title=name,
                desc=f"排名：{rank} · 累计下载：{downloads:,}",
                hot=downloads,
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _parse_activity(payload: object, board_type: str) -> list[ListItem]:
    rows = payload if isinstance(payload, list) else []
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"))
        version = _text(row.get("version"))
        platform = _text(row.get("platform")) or "ruby"
        if not name:
            continue

        item_id = name if board_type == "latest" else f"{name}:{version}:{platform}"
        if item_id in seen_ids:
            continue

        downloads = _integer(row.get("downloads"))
        version_downloads = _integer(row.get("version_downloads"))
        info = _text(row.get("info"))
        authors = _text(row.get("authors"))
        licenses = row.get("licenses")
        license_text = (
            ", ".join(_text(value) for value in licenses if _text(value))
            if isinstance(licenses, list)
            else ""
        )
        desc_parts = []
        if version:
            desc_parts.append(f"版本：{version}")
        if board_type == "updated":
            desc_parts.append(f"平台：{platform}")
        if info:
            desc_parts.append(info)
        if license_text:
            desc_parts.append(f"许可证：{license_text}")
        if downloads is not None:
            desc_parts.append(f"累计下载：{downloads:,}")
        if version_downloads is not None:
            desc_parts.append(f"当前版本下载：{version_downloads:,}")

        project_url = _text(row.get("project_uri")) or (
            f"{_BASE_URL}/gems/{quote(name, safe='@+-._')}"
        )
        if board_type == "updated" and version:
            version_slug = version if platform == "ruby" else f"{version}-{platform}"
            url = (
                f"{_BASE_URL}/gems/{quote(name, safe='@+-._')}/versions/"
                f"{quote(version_slug, safe='@+-._')}"
            )
        else:
            url = project_url

        seen_ids.add(item_id)
        data.append(
            ListItem(
                id=item_id,
                title=f"{name} {version}".strip(),
                author=authors or None,
                desc=" · ".join(desc_parts) or None,
                hot=version_downloads if board_type == "updated" else downloads,
                timestamp=(
                    get_time(_text(row.get("version_created_at")))
                    if board_type == "updated"
                    else None
                ),
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _integer(value: object) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
