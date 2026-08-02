from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics, text_or_none

ROUTE_NAME = "usgs-earthquakes"
SOURCE_LINK = "https://earthquake.usgs.gov/earthquakes/map/"
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "USGS Earthquakes",
    "description": "USGS 最近 24 小时全球 M2.5+ 地震事件",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="全球地震",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://earthquake.usgs.gov/fdsnws/event/1/query",
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "format": "geojson",
            "starttime": _window_start(),
            "minmagnitude": "2.5",
            "orderby": "time",
            "limit": "100",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/geo+json,application/json",
            "Referer": SOURCE_LINK,
        },
    )

    data: list[NewsFlashItem] = []
    for feature in (result.data or {}).get("features") or []:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 3:
            continue
        item_id = text_or_none(feature.get("id"))
        place = text_or_none(properties.get("place")) or "Unknown location"
        detail_url = text_or_none(properties.get("url"))
        magnitude = properties.get("mag")
        if not item_id or not detail_url or not isinstance(magnitude, (int, float)):
            continue

        longitude, latitude, depth = coordinates[:3]
        tsunami = properties.get("tsunami") == 1
        data.append(
            NewsFlashItem(
                id=item_id,
                title=f"M{magnitude:g} · {place}",
                content=_content(magnitude, place, latitude, longitude, depth, tsunami),
                contentStatus="full",
                source="USGS Earthquake Hazards Program",
                isImportant=magnitude >= 6 or tsunami,
                tags=_labels(_magnitude_label(magnitude), properties.get("alert"), properties.get("status")),
                metrics=metrics(
                    magnitude=magnitude,
                    magnitudeType=text_or_none(properties.get("magType")),
                    place=place,
                    latitude=latitude,
                    longitude=longitude,
                    depthKm=depth,
                    tsunami=tsunami,
                    significance=properties.get("sig"),
                    feltReports=properties.get("felt"),
                    alert=text_or_none(properties.get("alert")),
                    status=text_or_none(properties.get("status")),
                    updated=get_time(properties.get("updated")),
                ),
                timestamp=get_time(properties.get("time")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data[:20]}


def _window_start() -> str:
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (current_hour - timedelta(days=1)).strftime("%Y-%m-%dT%H:00:00Z")


def _content(
    magnitude: float,
    place: str,
    latitude: object,
    longitude: object,
    depth: object,
    tsunami: bool,
) -> str:
    details = [f"Magnitude: M{magnitude:g}", f"Location: {place}"]
    if isinstance(depth, (int, float)):
        details.append(f"Depth: {depth:g} km")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        details.append(f"Coordinates: {latitude:g}, {longitude:g}")
    details.append(f"Tsunami flag: {'yes' if tsunami else 'no'}")
    return "\n".join(details)


def _magnitude_label(magnitude: float) -> str:
    if magnitude >= 7:
        return "M7+"
    if magnitude >= 6:
        return "M6+"
    if magnitude >= 5:
        return "M5+"
    return "M2.5+"


def _labels(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        label = text_or_none(value)
        if label and label not in result:
            result.append(label)
    return result
