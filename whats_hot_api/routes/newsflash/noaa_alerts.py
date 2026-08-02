from __future__ import annotations

from typing import Any

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics, text_or_none

ROUTE_NAME = "noaa-alerts"

SOURCE_LINK = "https://www.weather.gov/alerts"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "NOAA/NWS",
    "description": "美国国家气象局当前生效的 Severe 与 Extreme 级公共告警",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="严重气象告警",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://api.weather.gov/alerts/active"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"status": "actual", "severity": "Extreme,Severe"},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/geo+json",
            "Referer": SOURCE_LINK,
        },
    )

    data: list[NewsFlashItem] = []
    for feature in (result.data or {}).get("features") or []:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        if properties.get("category") != "Met":
            continue
        item_id = text_or_none(properties.get("id")) or text_or_none(feature.get("id"))
        headline = text_or_none(properties.get("headline"))
        event = text_or_none(properties.get("event"))
        detail_url = text_or_none(properties.get("@id")) or text_or_none(feature.get("id"))
        if not item_id or not detail_url or not (headline or event):
            continue

        description = text_or_none(properties.get("description")) or headline or event or ""
        instruction = text_or_none(properties.get("instruction"))
        full_content = description
        if instruction and instruction not in description:
            full_content = f"{description}\n\nSafety instructions:\n{instruction}"
        content, content_status = _bounded_content(full_content)
        latitude, longitude = _centroid(feature.get("geometry"))
        data.append(
            NewsFlashItem(
                id=item_id,
                title=headline or event or item_id,
                content=content,
                summary=description[:300] if len(description) > 300 else None,
                contentStatus=content_status,
                source=text_or_none(properties.get("senderName")) or "NOAA/NWS",
                isImportant=properties.get("severity") == "Extreme",
                tags=_labels(
                    event,
                    properties.get("severity"),
                    properties.get("urgency"),
                    properties.get("certainty"),
                ),
                metrics=metrics(
                    area=text_or_none(properties.get("areaDesc")),
                    severity=text_or_none(properties.get("severity")),
                    urgency=text_or_none(properties.get("urgency")),
                    certainty=text_or_none(properties.get("certainty")),
                    response=text_or_none(properties.get("response")),
                    sent=text_or_none(properties.get("sent")),
                    effective=text_or_none(properties.get("effective")),
                    onset=text_or_none(properties.get("onset")),
                    ends=text_or_none(properties.get("ends")),
                    expires=text_or_none(properties.get("expires")),
                    latitude=latitude,
                    longitude=longitude,
                ),
                timestamp=get_time(properties.get("sent")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    data.sort(
        key=lambda item: (
            1 if item.metrics.get("severity") == "Extreme" else 0,
            item.timestamp or 0,
        ),
        reverse=True,
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data[:20],
    }


def _bounded_content(value: str, limit: int = 1600) -> tuple[str, str]:
    normalized = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    if len(normalized) <= limit:
        return normalized, "full"
    return f"{normalized[:limit].rstrip()}…", "truncated"


def _labels(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        label = text_or_none(value)
        if label and label not in result:
            result.append(label)
    return result


def _centroid(geometry: Any) -> tuple[float | None, float | None]:
    if not isinstance(geometry, dict):
        return None, None
    coordinates = geometry.get("coordinates")
    geometry_type = geometry.get("type")
    if geometry_type == "Point" and _is_pair(coordinates):
        return float(coordinates[1]), float(coordinates[0])
    if geometry_type == "Polygon" and isinstance(coordinates, list) and coordinates:
        return _ring_centroid(coordinates[0])
    if (
        geometry_type == "MultiPolygon"
        and isinstance(coordinates, list)
        and coordinates
        and isinstance(coordinates[0], list)
        and coordinates[0]
    ):
        return _ring_centroid(coordinates[0][0])
    return None, None


def _ring_centroid(points: object) -> tuple[float | None, float | None]:
    if not isinstance(points, list):
        return None, None
    pairs = [point for point in points if _is_pair(point)]
    if not pairs:
        return None, None
    latitude = sum(float(point[1]) for point in pairs) / len(pairs)
    longitude = sum(float(point[0]) for point in pairs) / len(pairs)
    return round(latitude, 3), round(longitude, 3)


def _is_pair(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    )
