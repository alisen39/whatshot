from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "pypi"

type_map: dict[str, str] = {
    "month": "月下载榜",
    "week": "周下载榜",
    "day": "日下载榜",
    "updates": "最新发布",
    "new": "新项目",
    "size": "项目体积榜",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "PyPI",
    "description": "Python Package Index 下载、发布与项目体积榜单",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://pypi.org/",
}

_PYPI_BASE = "https://pypi.org"
_PYPISTATS_TOP_URL = "https://pypistats.org/top"
_DOWNLOAD_BOARD_INDEX = {"day": 0, "week": 1, "month": 2}
_SIZE_MULTIPLIERS = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
}
_SIZE_RE = re.compile(r"^([\d.]+)\s*(B|KB|MB|GB|TB)$", re.IGNORECASE)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "month")
    selected = requested if requested in type_map else "month"
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
    if board_type in _DOWNLOAD_BOARD_INDEX:
        result = await get(
            url=_PYPISTATS_TOP_URL,
            no_cache=no_cache,
            response_type="text",
            headers=_html_headers(),
        )
        boards = _parse_download_boards(result.data or "")
        index = _DOWNLOAD_BOARD_INDEX[board_type]
        data = boards[index] if len(boards) > index else []
    elif board_type == "size":
        result = await get(
            url=f"{_PYPI_BASE}/stats/",
            no_cache=no_cache,
            response_type="text",
            headers=_html_headers(),
        )
        data = _parse_size_board(result.data or "")
    else:
        feed_name = "updates" if board_type == "updates" else "packages"
        result = await get(
            url=f"{_PYPI_BASE}/rss/{feed_name}.xml",
            no_cache=no_cache,
            response_type="text",
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )
        data = _parse_release_feed(result.data or "", board_type)

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_download_boards(html: str) -> list[list[ListItem]]:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1", string=lambda value: value and "Most downloaded" in value)
    outer_table = heading.find_next("table") if heading else None
    if outer_table is None:
        return []

    boards: list[list[ListItem]] = []
    for table in outer_table.find_all("table"):
        items: list[ListItem] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 3:
                continue
            name = cells[1].get_text(" ", strip=True)
            downloads = _integer(cells[2].get_text(" ", strip=True))
            if not name or downloads is None:
                continue
            rank = len(items) + 1
            url = f"{_PYPI_BASE}/project/{name}/"
            items.append(
                ListItem(
                    id=name,
                    title=name,
                    desc=f"排名：{rank} · 下载量：{downloads:,}",
                    hot=downloads,
                    url=url,
                    mobileUrl=url,
                )
            )
        if items:
            boards.append(items)
    return boards


def _parse_release_feed(xml: str, board_type: str) -> list[ListItem]:
    root = ET.fromstring(xml)
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in root.findall("./channel/item"):
        url = _xml_text(row, "link")
        path_parts = _project_path_parts(url)
        if not path_parts:
            continue

        project = path_parts[0]
        version = path_parts[1] if len(path_parts) > 1 else ""
        item_id = f"{project}:{version}" if version else project
        if item_id in seen_ids:
            continue

        summary = _xml_text(row, "description")
        desc_parts = []
        if version:
            desc_parts.append(f"版本：{version}")
        if summary and summary != "None":
            desc_parts.append(summary)

        title = _xml_text(row, "title")
        if board_type == "new":
            title = project
        elif not title:
            title = " ".join(part for part in (project, version) if part)

        seen_ids.add(item_id)
        data.append(
            ListItem(
                id=item_id,
                title=title,
                author=_xml_text(row, "author") or None,
                desc=" · ".join(desc_parts) or None,
                timestamp=_rfc822_ms(_xml_text(row, "pubDate")),
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _parse_size_board(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    caption = soup.find(
        "caption",
        string=lambda value: value and "Statistics by project" in value,
    )
    table = caption.find_parent("table") if caption else None
    body = table.find("tbody") if table else None
    if body is None:
        return []

    data: list[ListItem] = []
    for row in body.find_all("tr"):
        name_node = row.find("th")
        size_node = row.find("td")
        name = name_node.get_text(" ", strip=True) if name_node else ""
        size_label = size_node.get_text(" ", strip=True) if size_node else ""
        if not name or name == "All of PyPI" or not size_label:
            continue
        rank = len(data) + 1
        url = f"{_PYPI_BASE}/project/{name}/"
        data.append(
            ListItem(
                id=name,
                title=name,
                desc=f"排名：{rank} · 发布文件总体积：{size_label}",
                hot=_size_bytes(size_label),
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _project_path_parts(url: str) -> list[str]:
    parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    return parts[1:] if parts and parts[0] == "project" else []


def _xml_text(row: ET.Element, tag: str) -> str:
    node = row.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _rfc822_ms(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _integer(value: object) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _size_bytes(value: str) -> int | None:
    match = _SIZE_RE.match(value.strip())
    if not match:
        return None
    return round(float(match.group(1)) * _SIZE_MULTIPLIERS[match.group(2).upper()])


def _html_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
