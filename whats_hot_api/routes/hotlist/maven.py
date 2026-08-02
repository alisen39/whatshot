from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "maven"

type_map: dict[str, str] = {
    "popular-packages": "近 90 天热门包",
    "popular-namespaces": "近 90 天热门命名空间",
    "latest": "最新发布",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Maven Central",
    "description": "Maven Central 热门 Java 包、命名空间与最新发布",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
    "link": "https://central.sonatype.com/",
}

_CENTRAL_URL = "https://central.sonatype.com/"
_SEARCH_URL = "https://search.maven.org/solrsearch/select"
_LATEST_LIMIT = 100
_INTEGER_RE = re.compile(r"([\d,]+)")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "popular-packages")
    selected = requested if requested in type_map else "popular-packages"
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
    if board_type == "latest":
        result = await get(
            url=_SEARCH_URL,
            params={
                "q": "*:*",
                "rows": str(_LATEST_LIMIT),
                "wt": "json",
            },
            no_cache=no_cache,
            response_type="json",
            cache_key=f"{_SEARCH_URL}?q=*:*&rows={_LATEST_LIMIT}&wt=json",
            headers=_headers("application/json"),
        )
        data = _parse_latest(result.data or {})
    else:
        result = await get(
            url=_CENTRAL_URL,
            no_cache=no_cache,
            response_type="text",
            headers=_headers("text/html,application/xhtml+xml"),
        )
        data = _parse_popular(result.data or "", board_type)

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_popular(html: str, board_type: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    heading_text = (
        "Most Popular Packages in Last 90 Days"
        if board_type == "popular-packages"
        else "Most Popular Namespaces in Last 90 Days"
    )
    heading = next(
        (
            node
            for node in soup.select("h2")
            if node.get_text(" ", strip=True) == heading_text
        ),
        None,
    )
    if heading is None:
        return []
    listing = heading.find_next("ul")
    if listing is None:
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in listing.find_all("li", recursive=False):
        rank = len(data) + 1
        item = (
            _popular_package_item(row, rank)
            if board_type == "popular-packages"
            else _popular_namespace_item(row, rank)
        )
        if item is None or item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
    return data


def _popular_package_item(row: object, rank: int) -> ListItem | None:
    anchor = row.select_one(
        '[data-test="component-card-name-link"][href^="/artifact/"]'
    )
    if anchor is None:
        return None
    href = _text(anchor.get("href"))
    parts = href.strip("/").split("/")
    if len(parts) < 3:
        return None

    group_id = parts[1]
    artifact_id = parts[2]
    if not group_id or not artifact_id:
        return None

    version_node = row.select_one('[data-test="latest-version-metadata"]')
    published_node = row.select_one('[data-test="published-metadata"]')
    used_node = row.select_one('[data-test="used-in-metadata"]')
    version = version_node.get_text(" ", strip=True) if version_node else ""
    published = published_node.get_text(" ", strip=True) if published_node else ""
    used_in = _integer(used_node.get_text(" ", strip=True)) if used_node else None

    desc_parts = [f"近 90 天热门排名：{rank}"]
    if version:
        desc_parts.append(f"最新版本：{version}")
    if published:
        desc_parts.append(f"发布于：{published}")
    if used_in is not None:
        desc_parts.append(f"被引用：{used_in:,} 个项目")

    url = urljoin(_CENTRAL_URL, href)
    return ListItem(
        id=f"{group_id}:{artifact_id}",
        title=artifact_id,
        author=group_id,
        desc=" · ".join(desc_parts),
        url=url,
        mobileUrl=url,
    )


def _popular_namespace_item(row: object, rank: int) -> ListItem | None:
    anchor = row.select_one('a[href^="/namespace/"]')
    if anchor is None:
        return None
    namespace = anchor.get_text(" ", strip=True)
    href = _text(anchor.get("href"))
    if not namespace or not href:
        return None

    projects = _integer(row.get_text(" ", strip=True).removeprefix(namespace))
    desc = f"近 90 天热门排名：{rank}"
    if projects is not None:
        desc += f" · 包含项目：{projects:,}"
    url = urljoin(_CENTRAL_URL, href)
    return ListItem(
        id=namespace,
        title=namespace,
        desc=desc,
        url=url,
        mobileUrl=url,
    )


def _parse_latest(payload: object) -> list[ListItem]:
    if not isinstance(payload, dict):
        return []
    response = payload.get("response")
    if not isinstance(response, dict):
        return []
    rows = response.get("docs")
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows[:_LATEST_LIMIT]:
        if not isinstance(row, dict):
            continue
        group_id = _text(row.get("g"))
        artifact_id = _text(row.get("a"))
        version = _text(row.get("latestVersion"))
        if not group_id or not artifact_id or not version:
            continue
        item_id = f"{group_id}:{artifact_id}:{version}"
        if item_id in seen_ids:
            continue

        packaging = _text(row.get("p"))
        repository = _text(row.get("repositoryId"))
        version_count = _integer(row.get("versionCount"))
        desc_parts = [f"最新发布排名：{len(data) + 1}", f"版本：{version}"]
        if packaging:
            desc_parts.append(f"类型：{packaging}")
        if version_count is not None:
            desc_parts.append(f"版本数：{version_count:,}")
        if repository:
            desc_parts.append(f"仓库：{repository}")

        url = (
            f"{_CENTRAL_URL.rstrip('/')}/artifact/"
            f"{quote(group_id, safe='')}/{quote(artifact_id, safe='')}/"
            f"{quote(version, safe='')}"
        )
        seen_ids.add(item_id)
        data.append(
            ListItem(
                id=item_id,
                title=f"{artifact_id} {version}",
                author=group_id,
                desc=" · ".join(desc_parts),
                timestamp=get_time(row.get("timestamp")),
                url=url,
                mobileUrl=url,
            )
        )
    return data


def _headers(accept: str) -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _integer(value: object) -> int | None:
    match = _INTEGER_RE.search(str(value or ""))
    if match is None:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None
