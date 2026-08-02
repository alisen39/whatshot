from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "solidot"

SOURCE_LINK = "https://www.solidot.org/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Solidot",
    "description": "Solidot 奇客资讯",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="资讯",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    soup = BeautifulSoup(result.data, "lxml")
    data: list[ListItem] = []
    for block in soup.select(".block_m"):
        links = block.select(".bg_htit a")
        title_el = links[-1] if links else None
        href = title_el.get("href") if title_el else ""
        title = title_el.get_text(strip=True) if title_el else ""
        if not title or not href:
            continue

        talk_text = ""
        talk_el = block.select_one(".talk_time")
        if talk_el:
            talk_text = talk_el.get_text(" ", strip=True)
        url = urljoin(SOURCE_LINK, href)
        data.append(
            ListItem(
                id=_story_id(href) or url,
                title=title,
                author=_author_from_talk(talk_text),
                desc=_description(block),
                timestamp=_time_from_talk(talk_text),
                url=url,
                mobileUrl=url,
            )
        )
    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _story_id(href: str) -> str | None:
    match = re.search(r"sid=(\d+)", href)
    return match.group(1) if match else None


def _author_from_talk(text: str) -> str | None:
    if "发表于" not in text:
        return None
    author = text.split("发表于", 1)[0].strip()
    return re.sub(r"\s*\(\d+\)\s*$", "", author).strip() or None


def _time_from_talk(text: str) -> int | None:
    match = re.search(
        r"发表于\s*(\d{4})年(\d{2})月(\d{2})日\s+(\d{2})时(\d{2})分",
        text,
    )
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    return get_time(f"{year}-{month}-{day} {hour}:{minute}")


def _description(block) -> str | None:  # noqa: ANN001
    desc_el = block.select_one(".p_mainnew")
    if not desc_el:
        return None
    return desc_el.get_text(" ", strip=True) or None
