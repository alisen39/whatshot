from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "youdao"

type_map: dict[str, str] = {
    "popular-courses": "热门课程",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "有道精品课",
    "description": "有道精品课首页公开热门课程",
    "params": {
        "type": {
            "name": "榜单类型",
            "type": type_map,
        },
    },
    "link": "https://ke.youdao.com/",
}

_SOURCE_URL = "https://ke.youdao.com/?position=courseIndex"
_COURSE_URL = "https://ke.youdao.com/course/detail/{course_id}"
_COURSE_LINK_RE = re.compile(r"/course/detail/(\d+)")
_MAX_ITEMS = 20


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "popular-courses")
    selected = requested if requested in type_map else "popular-courses"
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_SOURCE_URL,
        no_cache=no_cache,
        cache_key="youdao:popular-courses",
        response_type="text",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_popular_courses(result.data),
    }


def _parse_popular_courses(payload: object) -> list[ListItem]:
    if not isinstance(payload, str) or not payload.strip():
        return []
    soup = BeautifulSoup(payload, "lxml")
    rows = _state_rows(soup)
    dom_ids = _popular_course_dom_ids(soup)
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= _MAX_ITEMS
        or len(dom_ids) != len(rows)
    ):
        return []

    items: list[ListItem] = []
    seen_ids: set[int] = set()
    for row in rows:
        item = _course_item(row)
        if item is None:
            return []
        course_id = int(item.id)
        if course_id in seen_ids:
            return []
        seen_ids.add(course_id)
        items.append(item)
    if [int(item.id) for item in items] != dom_ids:
        return []
    return items


def _state_rows(soup: BeautifulSoup) -> object:
    scripts = [
        script.string
        for script in soup.find_all("script")
        if script.string and "window.App=" in script.string
    ]
    if len(scripts) != 1:
        return None
    script = scripts[0]
    start = script.index("window.App=") + len("window.App=")
    try:
        app, _ = json.JSONDecoder().raw_decode(script[start:])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(app, dict):
        return None
    state = app.get("state")
    home = state.get("home") if isinstance(state, dict) else None
    return home.get("popularCourse") if isinstance(home, dict) else None


def _popular_course_dom_ids(soup: BeautifulSoup) -> list[int]:
    headings = [
        node
        for node in soup.find_all(["h1", "h2", "h3", "h4"])
        if _clean_text(node.get_text(" ", strip=True)) == "热门课程"
    ]
    if len(headings) != 1 or headings[0].parent is None:
        return []
    ids: list[int] = []
    for anchor in headings[0].parent.select(
        'a[href*="/course/detail/"][href*="inLoc=web_home_popular"]'
    ):
        href = _clean_text(anchor.get("href"))
        match = _COURSE_LINK_RE.search(href)
        if match is not None:
            ids.append(int(match.group(1)))
    return ids if len(ids) == len(set(ids)) else []


def _course_item(row: object) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    course_id = _positive_integer(row.get("id"))
    title = _clean_text(row.get("title"))
    course_title = _clean_text(row.get("courseTitle"))
    category = _clean_text(row.get("categoryName"))
    sale_count = _nonnegative_integer(row.get("courseSaleNum"))
    lesson_count = _nonnegative_integer(row.get("lessonNum"))
    price = _nonnegative_number(row.get("courseSalePrice"))
    hidden_count = row.get("hideNum")
    hidden_lessons = row.get("hideLessonNum")
    teachers = row.get("teacherList")
    expire_date = _clean_text(row.get("expireDate"))
    if (
        course_id is None
        or not title
        or title != course_title
        or not category
        or row.get("status") != 1
        or row.get("itemType") != 1
        or sale_count is None
        or lesson_count is None
        or price is None
        or not isinstance(hidden_count, bool)
        or not isinstance(hidden_lessons, bool)
        or not isinstance(teachers, list)
        or not teachers
        or _parse_datetime(expire_date) is None
    ):
        return None

    teacher_names = [
        _clean_text(teacher.get("name"))
        for teacher in teachers
        if isinstance(teacher, dict) and _clean_text(teacher.get("name"))
    ]
    if not teacher_names:
        return None

    parts = [category]
    course_time = _clean_text(row.get("courseTime"))
    if course_time:
        parts.append(course_time)
    if not hidden_lessons:
        parts.append(f"{lesson_count} 课时")
    parts.append("免费" if price == 0 else f"￥{price:g}")
    parts.append(f"报名截止：{expire_date}")

    cover = None
    for teacher in teachers:
        if not isinstance(teacher, dict):
            continue
        candidate = _ydstatic_url(teacher.get("imgUrl"))
        if candidate:
            cover = candidate
            break
    url = _COURSE_URL.format(course_id=course_id)
    return ListItem(
        id=str(course_id),
        title=title,
        author="、".join(dict.fromkeys(teacher_names)),
        desc=" · ".join(parts),
        hot=None if hidden_count else sale_count,
        cover=cover,
        url=url,
        mobileUrl=url,
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _positive_integer(value: object) -> int | None:
    number = _nonnegative_integer(value)
    return number if number is not None and number > 0 else None


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number == value else None


def _nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _ydstatic_url(value: object) -> str | None:
    url = _clean_text(value)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".ydstatic.com")
        or parsed.username
    ):
        return None
    return url


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())
