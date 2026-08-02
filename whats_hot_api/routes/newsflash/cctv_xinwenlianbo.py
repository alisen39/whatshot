from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "cctv-xinwenlianbo"

SOURCE_LINK = "https://tv.cctv.com/lm/xwlb/"
_DAY_PATTERN = re.compile(r"^\d{8}$")

ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "央视新闻联播",
    "description": "央视《新闻联播》每日节目单",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_day = request.query_params.get("day")
    explicit_day = requested_day if requested_day and _DAY_PATTERN.fullmatch(requested_day) else None
    day = explicit_day or _today()
    list_data = await _get_day(day, no_cache)
    if not explicit_day and not list_data["data"]:
        day = _previous_day(day)
        list_data = await _get_day(day, no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=f"{day} 节目单",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_day(day: str, no_cache: bool) -> dict[str, Any]:
    page_url = f"https://tv.cctv.com/lm/xwlb/day/{day}.shtml"
    try:
        result = await get(
            url=page_url,
            no_cache=no_cache,
            ttl=config.NEWSFLASH_CACHE_TTL,
            response_type="text",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml",
                "Referer": SOURCE_LINK,
            },
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                "from_cache": False,
                "update_time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "data": [],
            }
        raise
    soup = BeautifulSoup(result.data or "", "lxml")
    data: list[NewsFlashItem] = []
    for row in soup.select("li"):
        anchor = row.select_one(":scope > a[title][href]")
        if anchor is None or anchor.select_one(".sql0") is not None:
            continue
        title = _clean_title(anchor.get("title") or anchor.get_text(" ", strip=True))
        item_url = urljoin(page_url, str(anchor.get("href") or "").strip())
        if not title or not item_url:
            continue
        image = row.select_one(".image img[src]")
        duration = row.select_one(".image span")
        cover = urljoin(page_url, str(image.get("src"))) if image else None
        duration_text = duration.get_text(" ", strip=True) if duration else None
        data.append(
            NewsFlashItem(
                id=_item_id(item_url),
                title=title,
                content=title,
                contentStatus="summary",
                source="央视新闻联播",
                images=[cover] if cover else [],
                metrics={"duration": duration_text} if duration_text else {},
                timestamp=get_time(
                    f"{day[:4]}-{day[4:6]}-{day[6:]} 19:00:00"
                ),
                url=item_url,
                mobileUrl=item_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _previous_day(day: str) -> str:
    value = datetime.strptime(day, "%Y%m%d") - timedelta(days=1)
    return value.strftime("%Y%m%d")


def _clean_title(value: object) -> str:
    return re.sub(r"^\[视频\]\s*", "", str(value or "").strip())


def _item_id(url: str) -> str:
    filename = url.rstrip("/").rsplit("/", 1)[-1]
    return filename.removesuffix(".shtml")
