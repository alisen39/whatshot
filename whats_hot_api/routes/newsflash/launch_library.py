from __future__ import annotations

from datetime import datetime, timezone

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_urls, metrics, text_or_none

ROUTE_NAME = "launch-library"

SOURCE_LINK = "https://thespacedevs.com/llapi"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Launch Library 2",
    "description": "全球未来航天发射任务日程、状态与任务元数据",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="未来发射任务",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"limit": "10"},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    data: list[NewsFlashItem] = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for item in (result.data or {}).get("results") or []:
        item_id = text_or_none(item.get("id"))
        title = text_or_none(item.get("name"))
        detail_url = text_or_none(item.get("url"))
        net = get_time(item.get("net"))
        if not item_id or not title or not detail_url or net is None or net < now_ms:
            continue

        mission = item.get("mission") if isinstance(item.get("mission"), dict) else {}
        orbit = mission.get("orbit") if isinstance(mission.get("orbit"), dict) else {}
        provider = (
            item.get("launch_service_provider")
            if isinstance(item.get("launch_service_provider"), dict)
            else {}
        )
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        pad = item.get("pad") if isinstance(item.get("pad"), dict) else {}
        country = pad.get("country") if isinstance(pad.get("country"), dict) else {}
        image = item.get("image") if isinstance(item.get("image"), dict) else {}
        description = text_or_none(mission.get("description")) or _fallback_content(
            title=title,
            status=text_or_none(status.get("name")),
            provider=text_or_none(provider.get("name")),
            pad=text_or_none(pad.get("name")),
        )
        content, content_status = _bounded_content(description)

        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=content,
                summary=description[:300] if len(description) > 300 else None,
                contentStatus=content_status,
                source=text_or_none(provider.get("name")) or "Launch Library 2",
                tags=_labels(
                    status.get("name"),
                    mission.get("type"),
                    orbit.get("name"),
                    country.get("name"),
                ),
                images=compact_urls(image.get("image_url")),
                metrics=metrics(
                    status=text_or_none(status.get("name")),
                    probability=item.get("probability"),
                    weatherConcerns=text_or_none(item.get("weather_concerns")),
                    missionName=text_or_none(mission.get("name")),
                    missionType=text_or_none(mission.get("type")),
                    orbit=text_or_none(orbit.get("name")),
                    pad=text_or_none(pad.get("name")),
                    country=text_or_none(country.get("name")),
                    latitude=pad.get("latitude"),
                    longitude=pad.get("longitude"),
                    windowStart=text_or_none(item.get("window_start")),
                    windowEnd=text_or_none(item.get("window_end")),
                    lastUpdated=text_or_none(item.get("last_updated")),
                ),
                timestamp=net,
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    data.sort(key=lambda entry: entry.timestamp or 0)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _fallback_content(
    *,
    title: str,
    status: str | None,
    provider: str | None,
    pad: str | None,
) -> str:
    details = [value for value in (status, provider, pad) if value]
    return " · ".join([title, *details])


def _bounded_content(value: str, limit: int = 1200) -> tuple[str, str]:
    normalized = "\n".join(line.strip() for line in value.splitlines() if line.strip())
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
