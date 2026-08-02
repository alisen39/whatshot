from __future__ import annotations

from typing import Any

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, metrics, text_or_none

ROUTE_NAME = "nasa-eonet"

SOURCE_LINK = "https://eonet.gsfc.nasa.gov/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "NASA EONET",
    "description": "NASA 全球开放自然灾害事件追踪",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="开放自然事件",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://eonet.gsfc.nasa.gov/api/v3/events"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"status": "open", "limit": "60"},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    events: list[tuple[dict[str, Any], dict[str, Any], float, float]] = []
    for event in (result.data or {}).get("events") or []:
        geometry = _latest_geometry(event)
        coordinates = geometry.get("coordinates") or []
        if (
            len(coordinates) < 2
            or not isinstance(coordinates[0], (int, float))
            or not isinstance(coordinates[1], (int, float))
        ):
            continue
        events.append((event, geometry, float(coordinates[0]), float(coordinates[1])))

    events.sort(key=lambda row: str(row[1].get("date") or ""), reverse=True)
    data: list[NewsFlashItem] = []
    for event, geometry, longitude, latitude in events[:20]:
        event_id = text_or_none(event.get("id"))
        title = text_or_none(event.get("title"))
        if not event_id or not title:
            continue
        categories = compact_strings(event.get("categories"))
        sources = event.get("sources") or []
        primary_source = sources[0] if sources and isinstance(sources[0], dict) else {}
        source_name = text_or_none(primary_source.get("id")) or "NASA EONET"
        event_url = text_or_none(event.get("link")) or SOURCE_LINK
        detail_url = text_or_none(primary_source.get("url")) or event_url
        description = text_or_none(event.get("description"))
        magnitude_value = geometry.get("magnitudeValue")
        magnitude_unit = text_or_none(geometry.get("magnitudeUnit"))
        content_parts = [*categories]
        if magnitude_value is not None:
            content_parts.append(f"{magnitude_value:g} {magnitude_unit or ''}".strip())
        content_parts.append(f"{latitude:g}, {longitude:g}")
        data.append(
            NewsFlashItem(
                id=event_id,
                title=title,
                content=description or " · ".join(content_parts),
                summary=description,
                contentStatus="full",
                source=source_name,
                tags=categories,
                metrics=metrics(
                    latitude=latitude,
                    longitude=longitude,
                    magnitude=magnitude_value,
                    magnitudeUnit=magnitude_unit,
                    geometryType=text_or_none(geometry.get("type")),
                    eventUrl=event_url,
                ),
                timestamp=get_time(geometry.get("date")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _latest_geometry(event: dict[str, Any]) -> dict[str, Any]:
    geometries = event.get("geometry") or []
    latest = geometries[-1] if geometries else {}
    return latest if isinstance(latest, dict) else {}
