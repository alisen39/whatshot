from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "wikidata"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Wikidata",
    "description": "Wikidata 社区整理发布的官方每周动态汇总",
    "link": "https://www.wikidata.org/wiki/Wikidata:Status_updates",
}

_API_URL = "https://www.wikidata.org/w/api.php"
_PAGE_URL = "https://www.wikidata.org/wiki/Wikidata:Status_updates/{date_slug}"
_TITLE_RE = re.compile(r"^Wikidata:Status updates/(20\d{2}) (\d{2}) (\d{2})$")
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="官方周报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    today = datetime.now(timezone.utc).date()
    results = []
    rows: list[dict] = []
    for year in (today.year, today.year - 1):
        query = urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "list": "allpages",
                "apnamespace": "4",
                "apprefix": f"Status updates/{year}",
                "aplimit": str(_MAX_ITEMS),
                "apdir": "descending",
                "approp": "ids",
            }
        )
        result = await get(
            url=f"{_API_URL}?{query}",
            no_cache=no_cache,
            response_type="json",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
            cache_key=f"wikidata:status-updates:{year}:{_MAX_ITEMS}",
        )
        results.append(result)
        rows.extend(_response_rows(result.data))

    return {
        "from_cache": all(result.from_cache for result in results),
        "update_time": max(result.update_time for result in results),
        "data": _parse_rows(rows, today),
    }


def _response_rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("error") is not None:
        return []
    query = payload.get("query")
    if not isinstance(query, dict):
        return []
    rows = query.get("allpages")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return []
    return rows


def _parse_rows(rows: list[dict], today: date) -> list[ListItem]:
    records: list[tuple[date, int]] = []
    seen_ids: set[int] = set()
    seen_dates: set[date] = set()
    for row in rows:
        page_id = row.get("pageid")
        title = row.get("title")
        match = _TITLE_RE.fullmatch(title) if isinstance(title, str) else None
        if not isinstance(page_id, int) or page_id <= 0 or match is None:
            continue
        try:
            published = date(*(int(value) for value in match.groups()))
        except ValueError:
            continue
        if published > today or page_id in seen_ids or published in seen_dates:
            continue
        seen_ids.add(page_id)
        seen_dates.add(published)
        records.append((published, page_id))

    records.sort(reverse=True)
    items = []
    for published, page_id in records[:_MAX_ITEMS]:
        iso_date = published.isoformat()
        url = _PAGE_URL.format(date_slug=iso_date.replace("-", "_"))
        items.append(
            ListItem(
                id=str(page_id),
                title=f"Wikidata 周报 · {iso_date}",
                author="Wikidata Community",
                desc="Wikidata 官方每周动态：工具、数据模型、项目与社区进展",
                timestamp=int(
                    datetime.combine(published, datetime.min.time(), timezone.utc).timestamp()
                    * 1000
                ),
                url=url,
                mobileUrl=url,
            )
        )
    return items
