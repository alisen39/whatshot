from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "huodongxing"
SOURCE_URL = "https://www.huodongxing.com/events"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ID_RE = re.compile(r"/event/(\d+)")
_DATE_RE = re.compile(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})")

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "活动行",
    "description": "活动行公开活动列表，按活动开始日期排序",
    "params": {"type": {"name": "榜单分类", "type": {"upcoming": "近期活动"}}},
    "link": SOURCE_URL,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=SOURCE_URL,
        no_cache=no_cache,
        response_type="text",
        cache_key=SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
    )
    data = _parse_events(result.data)
    return RouterData(
        **ROUTE_META,
        type="近期活动",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _text(node: object) -> str:
    return " ".join(str(node or "").split())


def _parse_start_timestamp(value: str) -> int | None:
    now = datetime.now(_SHANGHAI)
    relative = re.search(r"(今天|明天|后天)\s*(\d{1,2}):(\d{2})", value)
    if relative:
        offset = {"今天": 0, "明天": 1, "后天": 2}[relative.group(1)]
        hour, minute = int(relative.group(2)), int(relative.group(3))
        if hour > 23 or minute > 59:
            return None
        day = now.date().fromordinal(now.date().toordinal() + offset)
        return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=_SHANGHAI).timestamp() * 1000)
    match = _DATE_RE.search(value)
    if not match:
        return None
    month, day = int(match.group("month")), int(match.group("day"))
    try:
        year = now.year
        start = datetime(year, month, day, tzinfo=_SHANGHAI)
        # The page omits years; a late-December snapshot can contain January events.
        if (start.date() - now.date()).days < -180:
            start = datetime(year + 1, month, day, tzinfo=_SHANGHAI)
        return int(start.timestamp() * 1000)
    except ValueError:
        return None


def _parse_events(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html or "", "html.parser")
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in soup.select(".search-tab-content-item-mesh"):
        link = card.select_one("a.item-title[href*='/event/'], a[href*='/event/']")
        href = _text(link.get("href") if link else "")
        match = _ID_RE.search(href)
        title_node = card.select_one("a.item-title span") or card.select_one("a.item-title")
        title = _text(title_node.get_text(" ") if title_node else "")
        event_id = match.group(1) if match else ""
        if not event_id or not title or event_id in seen:
            continue
        seen.add(event_id)
        time_text = _text(card.select_one(".item-dress p").get_text(" ") if card.select_one(".item-dress p") else "")
        location = _text(card.select_one(".item-dress-pp").get_text(" ") if card.select_one(".item-dress-pp") else "")
        organizer_node = card.select_one(".item-bottom-left .user-name")
        organizer = _text(organizer_node.get_text(" ") if organizer_node else "") or None
        cover_node = card.select_one("img.item-logo")
        cover = _text(cover_node.get("src") if cover_node else "") or None
        canonical = f"https://www.huodongxing.com/event/{event_id}"
        desc = " · ".join(part for part in (time_text, location) if part) or None
        items.append(
            ListItem(
                id=event_id,
                title=title,
                url=canonical,
                mobileUrl=canonical,
                author=organizer,
                cover=cover,
                desc=desc,
                timestamp=_parse_start_timestamp(time_text),
            )
        )
        if len(items) >= 50:
            break
    return items
