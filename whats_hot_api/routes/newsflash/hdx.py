from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics, strip_html, text_or_none

ROUTE_NAME = "hdx"

SOURCE_LINK = "https://data.humdata.org/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "HDX",
    "description": "Humanitarian Data Exchange 最新更新的非归档人道数据集",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="最新人道数据集",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://data.humdata.org/api/3/action/package_search"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "q": "crisis OR disaster OR emergency",
            "fq": "archived:false",
            "rows": "15",
            "sort": "metadata_modified desc",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    payload = result.data or {}
    items = (payload.get("result") or {}).get("results") or []
    data: list[NewsFlashItem] = []
    for item in items:
        if item.get("archived") is True:
            continue
        item_id = text_or_none(item.get("id")) or text_or_none(item.get("name"))
        title = text_or_none(item.get("title"))
        slug = text_or_none(item.get("name"))
        if not item_id or not title or not slug:
            continue

        notes = " ".join(strip_html(item.get("notes")).split())
        content, content_status = _bounded_content(notes or title)
        organization = item.get("organization") if isinstance(item.get("organization"), dict) else {}
        source = (
            text_or_none(item.get("dataset_source"))
            or text_or_none(organization.get("title"))
            or "HDX"
        )
        detail_url = f"https://data.humdata.org/dataset/{slug}"
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=content,
                summary=notes[:300] or None,
                contentStatus=content_status,
                source=source,
                tags=_labels(item.get("groups"), item.get("tags")),
                metrics=metrics(
                    resourceCount=item.get("num_resources"),
                    metadataCreated=text_or_none(item.get("metadata_created")),
                    metadataModified=text_or_none(item.get("metadata_modified")),
                    archived=False,
                ),
                timestamp=get_time(item.get("metadata_modified")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _bounded_content(value: str, limit: int = 1200) -> tuple[str, str]:
    if len(value) <= limit:
        return value, "full"
    return f"{value[:limit].rstrip()}…", "truncated"


def _labels(*groups: object) -> list[str]:
    values: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if isinstance(item, dict):
                value = (
                    text_or_none(item.get("display_name"))
                    or text_or_none(item.get("title"))
                    or text_or_none(item.get("name"))
                )
            else:
                value = text_or_none(item)
            if value and value not in values:
                values.append(value)
    return values
