from __future__ import annotations

import html
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "openreview"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OpenReview",
    "description": "OpenReview 上 TMLR 最新接收的机器学习论文",
    "link": "https://openreview.net/group?id=TMLR",
}

_API_URL = "https://api2.openreview.net/notes/search"
_VENUE_ID = "TMLR"
_VENUE_LABEL = "Accepted by TMLR"
_ACCEPTED_INVITATION = "TMLR/-/Accepted"
_FETCH_LIMIT = 100
_MAX_ITEMS = 50
_ABSTRACT_LIMIT = 600
_TAG_RE = re.compile(r"<[^>]+>")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="TMLR 最新接收",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    body = {
        "content": {
            "venue": {
                "terms": [_VENUE_LABEL],
                "matchMethod": "match",
            }
        },
        "venueid": _VENUE_ID,
        "source": "forum",
        "sort": "tmdate:desc",
        "limit": _FETCH_LIMIT,
    }
    result = await post(
        url=_API_URL,
        body=body,
        no_cache=no_cache,
        cache_key="openreview:tmlr:accepted:tmdate-desc:100",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_notes(result.data),
    }


def _parse_notes(payload: object) -> list[ListItem]:
    rows = payload.get("notes") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    valid_rows = [
        row
        for row in rows
        if _is_public_accepted_tmlr_note(row)
    ]
    valid_rows.sort(
        key=lambda row: (
            _integer(row.get("pdate")) or 0,
            _integer(row.get("tmdate")) or 0,
            _clean_text(_content_value(row, "title")).casefold(),
        ),
        reverse=True,
    )

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    for row in valid_rows:
        item = _note_item(row)
        if item is None:
            continue
        title_key = _identity_text(item.title)
        if item.id in seen_ids or title_key in seen_titles:
            continue
        seen_ids.add(item.id)
        seen_titles.add(title_key)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _is_public_accepted_tmlr_note(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    readers = row.get("readers")
    invitations = row.get("invitations")
    return (
        _clean_text(_content_value(row, "venue")) == _VENUE_LABEL
        and _clean_text(_content_value(row, "venueid")) == _VENUE_ID
        and isinstance(readers, list)
        and "everyone" in readers
        and isinstance(invitations, list)
        and _ACCEPTED_INVITATION in invitations
    )


def _note_item(row: object) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    note_id = _clean_text(row.get("id"))
    title = _clean_text(_content_value(row, "title"))
    pdate = _integer(row.get("pdate"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", note_id) or not title or not pdate:
        return None

    authors = _string_list(_content_value(row, "authors"))
    author_ids = _string_list(_content_value(row, "authorids"))
    if not authors:
        authors = [_profile_name(value) for value in author_ids]
        authors = [value for value in authors if value]

    desc_parts = ["期刊：Transactions on Machine Learning Research"]
    abstract = _clean_text(_content_value(row, "abstract"))
    if abstract:
        desc_parts.append(f"摘要：{_truncate(abstract, _ABSTRACT_LIMIT)}")
    submission_length = _clean_text(_content_value(row, "submission_length"))
    if submission_length:
        desc_parts.append(f"篇幅：{submission_length}")
    code_url = _clean_text(_content_value(row, "code"))
    if code_url:
        desc_parts.append(f"代码：{code_url}")
    desc_parts.append(f"OpenReview ID：{note_id}")

    url = f"https://openreview.net/forum?id={note_id}"
    return ListItem(
        id=note_id,
        title=title,
        author=_author_label(authors) or None,
        desc=" · ".join(desc_parts),
        timestamp=get_time(pdate),
        url=url,
        mobileUrl=url,
    )


def _content_value(row: dict, key: str) -> object:
    content = row.get("content")
    field = content.get(key) if isinstance(content, dict) else None
    return field.get("value") if isinstance(field, dict) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _author_label(authors: list[str]) -> str:
    if not authors:
        return ""
    return ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")


def _profile_name(value: object) -> str:
    return re.sub(r"\d+$", "", _clean_text(value).lstrip("~")).replace("_", " ").strip()


def _clean_text(value: object) -> str:
    text = _TAG_RE.sub(" ", str(value or ""))
    return " ".join(html.unescape(text).split())


def _identity_text(value: object) -> str:
    return re.sub(r"[^\w]+", " ", _clean_text(value).casefold()).strip()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
