from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "openalex"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OpenAlex",
    "description": "OpenAlex 全球研究目录的最新期刊论文",
    "link": "https://openalex.org/works",
}

_API_URL = "https://api.openalex.org/works"
_MAX_ITEMS = 50
_TAG_RE = re.compile(r"<[^>]+>")
_SELECT_FIELDS = ",".join(
    (
        "id",
        "doi",
        "display_name",
        "publication_date",
        "cited_by_count",
        "type",
        "language",
        "authorships",
        "primary_location",
        "open_access",
        "primary_topic",
    )
)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="最新期刊论文",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    cutoff = _utc_today()
    filters = ",".join(
        (
            f"to_publication_date:{cutoff}",
            "type:article",
            "primary_location.source.type:journal",
            "has_doi:true",
            "has_abstract:true",
            "is_retracted:false",
            "is_paratext:false",
        )
    )
    params = {
        "filter": filters,
        "sort": "publication_date:desc,cited_by_count:desc,display_name:asc",
        "per_page": str(_MAX_ITEMS),
        "select": _SELECT_FIELDS,
    }
    result = await get(
        url=_API_URL,
        params=params,
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{_API_URL}?filter={filters}&sort={params['sort']}&per_page={_MAX_ITEMS}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_works(result.data),
    }


def _parse_works(payload: object) -> list[ListItem]:
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    for row in rows:
        item = _work_item(row)
        if item is None:
            continue
        doi = _doi(row.get("doi")) if isinstance(row, dict) else ""
        doi_key = doi.casefold()
        title_key = _identity_text(item.title)
        if (
            item.id in seen_ids
            or (doi_key and doi_key in seen_dois)
            or title_key in seen_titles
        ):
            continue
        seen_ids.add(item.id)
        if doi_key:
            seen_dois.add(doi_key)
        seen_titles.add(title_key)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _work_item(row: object) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    work_id = _openalex_id(row.get("id"))
    title = _clean_text(row.get("display_name"))
    doi = _doi(row.get("doi"))
    if not work_id or not title or not doi:
        return None

    authors = _authors(row.get("authorships"))
    location = row.get("primary_location")
    source = location.get("source") if isinstance(location, dict) else None
    venue = _clean_text(source.get("display_name")) if isinstance(source, dict) else ""
    topic = row.get("primary_topic")
    topic_name = _clean_text(topic.get("display_name")) if isinstance(topic, dict) else ""
    language = _clean_text(row.get("language"))
    is_open_access = bool(
        isinstance(row.get("open_access"), dict)
        and row["open_access"].get("is_oa")
    )

    desc_parts = []
    if venue:
        desc_parts.append(f"期刊：{venue}")
    if topic_name:
        desc_parts.append(f"主题：{topic_name}")
    if language:
        desc_parts.append(f"语言：{language}")
    desc_parts.append(f"OpenAlex ID：{work_id}")
    desc_parts.append(f"DOI：{doi}")
    if is_open_access:
        desc_parts.append("开放获取")

    url = f"https://doi.org/{quote(doi, safe='/')}"
    return ListItem(
        id=work_id,
        title=title,
        author=authors or None,
        desc=" · ".join(desc_parts),
        hot=_integer(row.get("cited_by_count")),
        timestamp=get_time(row.get("publication_date")),
        url=url,
        mobileUrl=url,
    )


def _authors(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names = []
    for authorship in value:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = _clean_text(author.get("display_name")) if isinstance(author, dict) else ""
        if name:
            names.append(name)
    if not names:
        return ""
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def _openalex_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    work_id = text.rsplit("/", 1)[-1].upper()
    return work_id if re.fullmatch(r"W\d+", work_id) else ""


def _doi(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    return text


def _clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    return " ".join(_TAG_RE.sub(" ", text).split())


def _identity_text(value: object) -> str:
    return re.sub(r"[^\w]+", " ", _clean_text(value).casefold()).strip()


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
